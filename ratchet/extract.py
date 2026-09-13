"""SourceItem -> Case. The only place prose becomes structure.

This file used to hand the model a menu of ten rules and ask it to pick one.
That works, and it is also the ceiling on the whole system: a menu written in
advance can only ever catch failures somebody already thought of. Shreya
Shankar's UIST 2024 study names the trap — **criteria drift**: *"users need
criteria to grade outputs, but grading outputs helps users define criteria."*
The criteria are supposed to move as you read real failures. A fixed menu cannot.

So the model no longer classifies. It reads one failure report and *names the
rule itself*, inventing the slug and writing the expectation. A complaint about
something nobody anticipated now produces a case instead of being discarded as
off-menu.

The cost of dropping the menu is that two people describing the same failure
produce two rules. That is what the subsumption pass fixes: for each candidate,
ask whether a rule already kept covers it (SPADE's trick), and if so merge
rather than duplicate. Candidates are considered strongest-first — a fix outranks
a complaint, and higher confidence outranks lower — so the survivor of a merge is
always the better-evidenced one.

Items that describe no checkable failure are dropped and counted. A dropped item
is a normal outcome, not an error — most chatter is chatter.
"""

from __future__ import annotations

import concurrent.futures as cf
import re

from .cases import Case
from .llm import complete_json
from .sources.base import SourceItem

EXTRACT_PROMPT = """You triage reports about a document generator that writes engagement letters.

Decide whether the ITEM below describes a specific, checkable failure of the
generated documents — something a test could verify by reading one document.

Say NO (checkable: false) for: general chatter, questions, status updates,
praise, deployment notes, or anything too vague to test.
Say YES for: a described defect in the output, OR a fix that repairs one — a fix
is a complaint with the answer attached, and is the strongest signal here.

If YES, name the rule yourself. Do not fit it to any predefined category.
  - rule_id: a short lower_snake_case slug for the underlying rule, general
    enough that another report of the same problem would produce the same slug.
    Name the RULE, not this one incident: prefer "fee_total_arithmetic" over
    "meridian_total_wrong".
  - expectation: ONE sentence stating what a CORRECT document does. Write it so
    that someone holding only that sentence and a document could decide the
    matter. This sentence is what the grader gets built from, so be concrete
    about the observable thing — a format, a section, a number that must agree.

ITEM
app: {app}
kind: {kind}
author: {author}
text:
{text}

Return ONLY JSON:
{{"checkable": true|false,
  "rule_id": "<lower_snake_case slug, or empty>",
  "title": "<six words naming the failure>",
  "expectation": "<one sentence: what a correct document does>",
  "is_fix": true|false,
  "confidence": 0.0-1.0}}"""


SUBSUME_PROMPT = """Two rules were derived independently from two different failure reports
about the same document generator. Decide whether they are the same rule.

They are the SAME if a single grader could check both — if checking A necessarily
checks B, or the two sentences describe one underlying requirement in different
words. They are DIFFERENT if a document could satisfy one and violate the other.

Be strict. Two rules about dates are not the same rule if one is about spelling a
month and the other is about which date comes first.

RULE A
id: {a_id}
expectation: {a_exp}

RULE B
id: {b_id}
expectation: {b_exp}

Return ONLY JSON: {{"same": true|false, "reason": "<one short sentence>"}}"""


SLUG_RE = re.compile(r"[^a-z0-9_]+")


def _slug(raw: str) -> str:
    s = SLUG_RE.sub("_", str(raw).strip().lower()).strip("_")
    return s[:40] or "unnamed_rule"


def _one(item: SourceItem) -> dict | None:
    data = complete_json(EXTRACT_PROMPT.format(
        app=item.app, kind=item.kind, author=item.author, text=item.text[:1500]))
    if not isinstance(data, dict):
        return {"_parse_failed": True, "item": item}
    if not data.get("checkable"):
        return None
    if not str(data.get("rule_id", "")).strip() or not str(data.get("expectation", "")).strip():
        # Claimed checkable but gave us nothing to check. That is a parse
        # failure, not a clean discard, and it gets counted as one.
        return {"_parse_failed": True, "item": item}
    return {"data": data, "item": item}


def _same_rule(a: dict, b: dict) -> bool:
    """SPADE's subsumption question, asked one pair at a time and cached."""
    data = complete_json(SUBSUME_PROMPT.format(
        a_id=a["rule_id"], a_exp=a["expectation"],
        b_id=b["rule_id"], b_exp=b["expectation"]))
    return bool(isinstance(data, dict) and data.get("same"))


def _score(d: dict) -> tuple[int, float]:
    """A fix outranks a complaint; within each, higher confidence wins."""
    try:
        conf = float(d.get("confidence", 0))
    except (TypeError, ValueError):
        conf = 0.0
    return (1 if d.get("is_fix") else 0, conf)


def dedupe(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """Collapse candidates that describe one rule. Returns (kept, merges).

    Strongest-first, so the rule that survives a merge is the better-evidenced
    one — which is how "prefer anything derived from a fix" is enforced without a
    special case. Identical slugs collapse for free; the model is only asked
    about pairs whose slugs already differ.
    """
    ordered = sorted(candidates, key=lambda c: (-_score(c["data"])[0],
                                                -_score(c["data"])[1],
                                                c["data"]["rule_id"]))
    kept: list[dict] = []
    merges: list[dict] = []

    for cand in ordered:
        d = cand["data"]
        match = next((k for k in kept if k["data"]["rule_id"] == d["rule_id"]), None)
        if match is None:
            for k in kept:
                if _same_rule(k["data"], d):
                    match = k
                    break
        if match is None:
            kept.append(cand)
        else:
            merges.append({"dropped": d["rule_id"], "into": match["data"]["rule_id"],
                           "dropped_expectation": d["expectation"]})
    return kept, merges


def extract(items: list[SourceItem], briefs: list[dict], workers: int = 6) -> tuple[list[Case], dict]:
    """Returns (cases, stats). One surviving rule becomes one case per brief:
    the complaint told us what to check, so we check it on every document."""
    results = []
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_one, items):
            results.append(r)

    stats = {"items": len(items), "parse_failed": 0, "not_checkable": 0, "accepted": 0}
    candidates: list[dict] = []

    for r in results:
        if r is None:
            stats["not_checkable"] += 1
            continue
        if r.get("_parse_failed"):
            stats["parse_failed"] += 1
            continue
        stats["accepted"] += 1
        r["data"]["rule_id"] = _slug(r["data"]["rule_id"])
        candidates.append(r)

    kept, merges = dedupe(candidates)

    cases: list[Case] = []
    for info in sorted(kept, key=lambda c: c["data"]["rule_id"]):
        d, item = info["data"], info["item"]
        rule = d["rule_id"]
        for b in briefs:
            cases.append(Case(
                id=f"{rule}::{b['id']}",
                rule=rule,
                title=d.get("title") or rule.replace("_", " "),
                expectation=d["expectation"],
                brief_id=b["id"],
                # Which grader actually runs is decided in judge.grade(), which
                # is the only module allowed to know. Extraction records the
                # criterion; it does not choose the instrument.
                grader="derived",
                source_app=item.app,
                source_id=item.external_id,
                source_text=item.text[:400],
                source_url=item.url,
                derived_from_fix=bool(d.get("is_fix")),
                meta={"confidence": d.get("confidence")},
            ))

    stats["rules"] = len(kept)
    stats["cases"] = len(cases)
    stats["merged"] = len(merges)
    stats["merges"] = merges
    return cases, stats
