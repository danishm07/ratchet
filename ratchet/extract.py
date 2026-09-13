"""SourceItem -> Case. The only place prose becomes structure.

One cached LLM call per source item. The model's job is narrow: decide whether
this item describes a real, checkable failure of the document generator and, if
so, which known rule it concerns. Narrow jobs are the ones models do reliably.

Items that describe no checkable failure are dropped and counted. A dropped item
is a normal outcome, not an error — most chatter is chatter.
"""

from __future__ import annotations

import concurrent.futures as cf
import json

from .cases import Case
from .llm import complete_json
from .sources.base import SourceItem

RULE_MENU = {
    "date":      "dates must read '14 June 2026'; no misspelled or abbreviated months",
    "totals":    "phase fees must sum to the stated total",
    "percent":   "a spelled-out percentage must match its numeral",
    "headings":  "numbered heading hierarchy",
    "legalname": "placeholder instead of an invented client legal entity",
    "daterange": "end date must fall after start date",
    "assume":    "an Assumptions section must be present",
    "currency":  "one currency symbol throughout",
    "termmatch": "stated term length must match the quoted engagement length",
    "excl":      "an Exclusions section must be present",
}

PROMPT = """You triage reports about a document generator that writes engagement letters.

Decide whether the ITEM below describes a specific, checkable failure of the
generated documents — something a test could verify. Then map it to exactly one
rule from the menu.

Say NO (checkable: false) for: general chatter, questions, status updates,
praise, deployment notes, or anything too vague to test.
Say YES for: a described defect in the output, OR a fix that repairs one — a fix
is a complaint with the answer attached, and is the strongest signal here.

RULE MENU:
{menu}

ITEM
app: {app}
kind: {kind}
author: {author}
text:
{text}

Return ONLY JSON:
{{"checkable": true|false,
  "rule": "<one key from the menu, or empty>",
  "title": "<six words naming the failure>",
  "expectation": "<one sentence: what a correct document does>",
  "is_fix": true|false,
  "confidence": 0.0-1.0}}"""


def _one(item: SourceItem) -> dict | None:
    menu = "\n".join(f"  {k}: {v}" for k, v in RULE_MENU.items())
    data = complete_json(PROMPT.format(
        menu=menu, app=item.app, kind=item.kind,
        author=item.author, text=item.text[:1500]))
    if not isinstance(data, dict):
        return {"_parse_failed": True, "item": item}
    if not data.get("checkable") or data.get("rule") not in RULE_MENU:
        return None
    return {"data": data, "item": item}


def extract(items: list[SourceItem], briefs: list[dict], workers: int = 6) -> tuple[list[Case], dict]:
    """Returns (cases, stats). One accepted item becomes one case per brief:
    the complaint told us what to check, so we check it on every document."""
    results = []
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_one, items):
            results.append(r)

    stats = {"items": len(items), "parse_failed": 0, "not_checkable": 0, "accepted": 0}
    seen_rules: dict[str, dict] = {}

    for r in results:
        if r is None:
            stats["not_checkable"] += 1
            continue
        if r.get("_parse_failed"):
            stats["parse_failed"] += 1
            continue
        stats["accepted"] += 1
        d, item = r["data"], r["item"]
        rule = d["rule"]
        # Keep the highest-confidence origin per rule, preferring a fix.
        prev = seen_rules.get(rule)
        score = (1 if d.get("is_fix") else 0, float(d.get("confidence", 0)))
        if prev is None or score > prev["score"]:
            seen_rules[rule] = {"d": d, "item": item, "score": score}

    cases: list[Case] = []
    for rule, info in sorted(seen_rules.items()):
        d, item = info["d"], info["item"]
        for b in briefs:
            cases.append(Case(
                id=f"{rule}::{b['id']}",
                rule=rule,
                title=d.get("title") or RULE_MENU[rule],
                expectation=d.get("expectation") or RULE_MENU[rule],
                brief_id=b["id"],
                grader="llm" if rule == "legalname" else "deterministic",
                source_app=item.app,
                source_id=item.external_id,
                source_text=item.text[:400],
                source_url=item.url,
                derived_from_fix=bool(d.get("is_fix")),
            ))
    stats["rules"] = len(seen_rules)
    stats["cases"] = len(cases)
    return cases, stats
