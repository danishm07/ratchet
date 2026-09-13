"""Generate a grader from a failure description, instead of picking one off a menu.

`judge.py` holds ten graders someone wrote by hand. That ceiling is the problem
Shreya Shankar names in UIST 2024 as **criteria drift**: *"users need criteria to
grade outputs, but grading outputs helps users define criteria."* A menu fixed in
advance is already behind the real failure distribution — it can only ever catch
failures somebody anticipated.

So: read the expectation, emit a grader. Two cached model calls, following the
G-Eval pattern (DeepEval / promptfoo) — derive the evaluation steps first, then
apply them.

**The generated artefact is a structured spec, never executable code.** Nothing
here `exec()`s anything a model wrote. A spec is inspectable before it runs,
cacheable by value, and diffable in review; generated Python is none of those and
buys almost nothing, because the common criteria are a regex, a number
comparison, or a rubric.

The spec kinds, in the order they are preferred (CLAUDE.md rule 4 — deterministic
graders win, so a model call is the last resort, not the first):

    regex_present   the document must contain something
    regex_absent    the document must not contain something
    numeric_match   a number in the document must equal a number in the brief
    llm_rubric      genuinely subjective; generated steps go to a model
"""

from __future__ import annotations

import concurrent.futures as cf
import functools
import json
import re
# aliased: GraderSpec has an attribute called `field`, which would otherwise
# shadow dataclasses.field inside the class body.
from dataclasses import dataclass, asdict, field as dc_field
from typing import Any, Literal, Sequence

from . import judge
from .cases import Case
from .judge import NUM_WORD, Verdict
from .llm import complete_json

KINDS = ("regex_present", "regex_absent", "numeric_match", "llm_rubric")

# Generated patterns run with these flags. Expectations are written in prose
# about a whole document, so a pattern author means "anywhere, any case" even
# when they do not say so.
FLAGS = re.IGNORECASE | re.MULTILINE

MAX_PATTERN = 400      # a longer "regex" is a model narrating, not a pattern
MAX_OUTPUT = 20000     # bound the text any generated pattern is run over

# Cheap catastrophic-backtracking guard: a quantified group whose body is itself
# quantified, e.g. (a+)+ or ([\d,]*)*. Python's re has no timeout, so patterns
# shaped like this are refused rather than run.
_NESTED_QUANT = re.compile(r"\([^()]*[+*]\)[+*]")


@dataclass
class GraderSpec:
    kind: Literal["regex_present", "regex_absent", "numeric_match", "llm_rubric"]
    pattern: str | None = None       # regex kinds, and the number-capture for numeric_match
    field: str | None = None         # numeric_match: which brief value to compare against
    steps: list[str] = dc_field(default_factory=list)  # llm_rubric: the generated evaluation steps
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def brief_fields(brief: dict) -> dict[str, float]:
    """The numeric values a `numeric_match` spec may compare against.

    Derived by introspecting the brief rather than hardcoded, so a different
    brief schema exposes a different menu without anyone editing this file.
    Lists of objects contribute a count and a sum per numeric key, which is what
    "the phase fees must sum to the total" needs.
    """
    out: dict[str, float] = {}
    for k, v in brief.items():
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out[k] = float(v)
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            out[f"{k}_count"] = float(len(v))
            keys = {s for x in v for s, y in x.items()
                    if isinstance(y, (int, float)) and not isinstance(y, bool)}
            for s in keys:
                out[f"{k}_{s}_sum"] = float(sum(x.get(s, 0) for x in v))
    return out


# --------------------------------------------------------------- derive_spec

SPEC_PROMPT = """You turn one expectation about a generated business document into a
GRADER SPECIFICATION: a small structured object that a program can execute to decide
whether one document meets that expectation.

Choose the CHEAPEST kind that can actually decide the expectation. A deterministic
check is always preferred over a model call — it is faster, free, and has no
agreement problem. Only choose llm_rubric when the criterion genuinely requires
judgement that no pattern or arithmetic can settle.

KINDS
  regex_present  The document PASSES if the pattern matches somewhere.
                 Use for "must contain / must include / must state X".
  regex_absent   The document PASSES if the pattern matches NOWHERE.
                 Use for "must never / must not contain / must avoid X".
  numeric_match  The document PASSES if a number found by the pattern equals a
                 value from the brief. The pattern MUST contain exactly one
                 capture group around the number. Set "field" to one of the
                 available brief fields below.
  llm_rubric     Subjective. Supply 3-5 short ordered evaluation steps instead of
                 a pattern.

REGEX NOTES
  - Python `re` syntax. Patterns run with IGNORECASE and MULTILINE already set,
    so do not add inline flags and do not worry about letter case.
  - The document is markdown. A heading may appear as "## Assumptions",
    "**5. Assumptions**" or "5. Assumptions" — a pattern for a section must
    tolerate all three.
  - Keep patterns short and readable. Never nest a quantifier inside a quantified
    group, e.g. `(x+)+`.

AVAILABLE BRIEF FIELDS (numeric_match only)
{fields}

EXPECTATION
{expectation}

Return ONLY JSON:
{{"kind": "regex_present|regex_absent|numeric_match|llm_rubric",
  "pattern": "<regex, or null for llm_rubric>",
  "field": "<one field name from the list, or null>",
  "steps": ["<step>", "..."],
  "rationale": "<one sentence: why this kind and this check>"}}"""


def derive_spec(expectation: str, fields: Sequence[str] = ()) -> GraderSpec:
    """One cached model call: expectation -> executable spec.

    A model that returns something unusable (bad kind, uncompilable pattern,
    unknown field) degrades to an `llm_rubric` over the raw expectation. That is
    a real, countable outcome and `rationale` says so — it is never silently
    treated as a working deterministic grader.
    """
    menu = "\n".join(f"  {f}" for f in fields) or "  (none available)"
    data = complete_json(SPEC_PROMPT.format(fields=menu, expectation=expectation.strip()))

    if not isinstance(data, dict) or data.get("kind") not in KINDS:
        return _fallback(expectation, "model returned no usable spec")

    kind = data["kind"]
    pattern = data.get("pattern") or None
    spec_field = data.get("field") or None
    steps = [str(s) for s in (data.get("steps") or []) if str(s).strip()]
    rationale = str(data.get("rationale", ""))[:300]

    if kind in ("regex_present", "regex_absent", "numeric_match"):
        problem = _pattern_problem(pattern)
        if problem:
            return _fallback(expectation, f"{kind} rejected: {problem}")
        if kind == "numeric_match":
            if re.compile(pattern).groups != 1:
                return _fallback(expectation, "numeric_match needs exactly one capture group")
            if spec_field not in set(fields):
                return _fallback(expectation, f"unknown brief field {spec_field!r}")

    return GraderSpec(kind=kind, pattern=pattern, field=spec_field,
                      steps=steps, rationale=rationale)


@functools.lru_cache(maxsize=512)
def _spec_cached(expectation: str, fields: tuple[str, ...]) -> GraderSpec:
    return derive_spec(expectation, fields)


def spec_for(expectation: str, brief: dict) -> GraderSpec:
    """The spec for one expectation, derived once per process.

    `derive_spec` is already cached on disk at the model layer, so this only
    saves re-parsing — but grading is 60 cases × 5 versions, and re-deriving the
    same spec 300 times is noise in the logs nobody needs.
    """
    return _spec_cached(expectation.strip(), tuple(sorted(brief_fields(brief))))


def _fallback(expectation: str, why: str) -> GraderSpec:
    return GraderSpec(
        kind="llm_rubric",
        steps=[f"Decide whether the document satisfies: {expectation.strip()}"],
        rationale=f"fell back to llm_rubric — {why}",
    )


def _pattern_problem(pattern: str | None) -> str | None:
    """Why this pattern must not be run, or None if it is safe to run."""
    if not pattern:
        return "no pattern supplied"
    if len(pattern) > MAX_PATTERN:
        return f"pattern is {len(pattern)} chars, over the {MAX_PATTERN} limit"
    if _NESTED_QUANT.search(pattern):
        return "nested quantifier risks catastrophic backtracking"
    try:
        re.compile(pattern)
    except re.error as e:
        return f"does not compile ({e})"
    return None


# ------------------------------------------------------------ grade_generated

RUBRIC_PROMPT = """You are grading ONE generated engagement letter against ONE criterion.

Work through the evaluation steps in order, then decide. Judge only the criterion
below — not the document's overall quality, tone or completeness.

CRITERION
{expectation}

EVALUATION STEPS
{steps}

BRIEF THE DOCUMENT WAS WRITTEN FROM
{brief}

DOCUMENT
{out}

Return ONLY JSON:
{{"passed": true|false,
  "reason": "<one sentence>",
  "quote": "<the exact phrase from the DOCUMENT that decides it, or empty>"}}"""


def grade_generated(spec: GraderSpec, output: str, brief: dict,
                    expectation: str = "") -> Verdict:
    """Execute a spec. Regex and numeric kinds cost nothing; only llm_rubric calls a model."""
    text = output[:MAX_OUTPUT]

    if spec.kind == "llm_rubric":
        return _grade_rubric(spec, text, brief, expectation)

    problem = _pattern_problem(spec.pattern)
    if problem:
        return Verdict(False, f"generated pattern unusable: {problem}",
                       grader=f"generated:{spec.kind}")
    rx = re.compile(spec.pattern, FLAGS)
    m = rx.search(text)
    hit = m.group(0).strip()[:160] if m else ""

    if spec.kind == "regex_present":
        if m:
            return Verdict(True, "the required pattern is present", hit,
                           grader="generated:regex_present")
        return Verdict(False, "the required pattern is absent",
                       grader="generated:regex_present")

    if spec.kind == "regex_absent":
        if m:
            return Verdict(False, f"forbidden pattern present: {hit!r}", hit,
                           grader="generated:regex_absent")
        return Verdict(True, "the forbidden pattern is absent",
                       grader="generated:regex_absent")

    if spec.kind == "numeric_match":
        return _grade_numeric(spec, rx, text, brief)

    return Verdict(False, f"unknown spec kind {spec.kind!r}", grader="generated")


def _grade_rubric(spec: GraderSpec, text: str, brief: dict, expectation: str) -> Verdict:
    """The generated steps, the brief and the document — and nothing else.

    Factored judging (CLAUDE.md): no transcript, no neighbouring case, no prior
    verdict. A judge that can see an earlier judgement conditions on it.
    """
    steps = "\n".join(f"  {i}. {s}" for i, s in enumerate(spec.steps, 1)) or "  1. Use your judgement."
    data = complete_json(RUBRIC_PROMPT.format(
        expectation=expectation.strip() or spec.rationale,
        steps=steps,
        brief=json.dumps(brief, indent=2),
        out=text[:3000]))
    if not isinstance(data, dict) or "passed" not in data:
        return Verdict(False, "generated rubric returned no parseable verdict",
                       grader="generated:llm_rubric")
    return Verdict(bool(data["passed"]), str(data.get("reason", ""))[:200],
                   str(data.get("quote", ""))[:160], grader="generated:llm_rubric")


def _number(raw: str) -> float | None:
    """A captured group as a number — digits, grouped digits, or a number word."""
    s = raw.strip().lower().replace(",", "").replace("$", "").replace("£", "").replace("€", "")
    try:
        return float(s)
    except ValueError:
        return float(NUM_WORD[s]) if s in NUM_WORD else None


def _grade_numeric(spec: GraderSpec, rx: re.Pattern, text: str, brief: dict) -> Verdict:
    want = brief_fields(brief).get(spec.field or "")
    if want is None:
        return Verdict(False, f"brief has no numeric field {spec.field!r}",
                       grader="generated:numeric_match")
    hits = rx.findall(text)
    if not hits:
        return Verdict(False, f"no number found to compare against {spec.field}",
                       grader="generated:numeric_match")
    for h in hits:
        got = _number(h if isinstance(h, str) else h[0])
        if got is None:
            continue
        if got != want:
            return Verdict(False,
                           f"document states {got:,.0f} but brief's {spec.field} is {want:,.0f}",
                           str(h)[:160], grader="generated:numeric_match")
        return Verdict(True, f"{got:,.0f} matches the brief's {spec.field}",
                       str(h)[:160], grader="generated:numeric_match")
    return Verdict(False, f"captured {hits[0]!r}, which is not a number",
                   str(hits[0])[:160], grader="generated:numeric_match")


# ----------------------------------------------- is the generated grader any good?

def reference_cases(rules: dict[str, str], briefs: list[dict]) -> list[Case]:
    """One case per reference rule per brief, built here rather than read from disk.

    `compare-graders` must not depend on what extraction happened to produce —
    extraction now invents its own slugs, so cases.json holds different rules on
    every corpus. Constructing the grid from the reference set is what makes this
    number reproducible by someone else from one command.
    """
    return [
        Case(id=f"{rule}::{b['id']}", rule=rule, title=rule, expectation=exp,
             brief_id=b["id"], grader="reference", source_app="reference",
             source_id=rule, source_text=exp)
        for rule, exp in sorted(rules.items())
        for b in briefs
    ]


def compare(rules: dict[str, str], payload: dict, briefs: list[dict],
            workers: int = 6) -> dict[str, Any]:
    """Generated graders vs the hand-written ones, over every case × version.

    The ten hand-written graders are the ground truth here — not because they are
    right in some absolute sense, but because they are the thing already validated
    against human labels. Agreement bounds how far generation can be trusted, and
    the disagreements are the interesting output: they say *where* generation
    fails, which a single percentage cannot.
    """
    by_id = {b["id"]: b for b in briefs}
    fields = sorted(brief_fields(briefs[0])) if briefs else []
    cases = reference_cases(rules, briefs)

    specs: dict[str, GraderSpec] = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {r: ex.submit(derive_spec, exp, fields) for r, exp in rules.items()}
        for r, f in futs.items():
            specs[r] = f.result()

    versions = payload["versions"]
    jobs = [(c, v) for v in versions for c in cases if c.rule in specs]

    def one(job: tuple[Case, str]) -> dict[str, Any]:
        c, v = job
        doc = payload["runs"][v]["docs"].get(c.brief_id)
        if doc is None:
            raise RuntimeError(
                f"compare-graders: no document for {c.brief_id} at {v} in latest.json")
        brief = by_id[c.brief_id]
        hand = judge.grade(c, doc, brief)
        gen = grade_generated(specs[c.rule], doc, brief, rules[c.rule])
        return {"case": c.id, "rule": c.rule, "version": v,
                "hand": hand.passed, "gen": gen.passed,
                "hand_reason": hand.reason, "gen_reason": gen.reason}

    rows: list[dict[str, Any]] = []
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(one, jobs):
            rows.append(r)

    per_rule: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = per_rule.setdefault(r["rule"], {"n": 0, "agree": 0, "kind": specs[r["rule"]].kind})
        d["n"] += 1
        d["agree"] += int(r["hand"] == r["gen"])

    agree = sum(1 for r in rows if r["hand"] == r["gen"])
    return {
        "n": len(rows),
        "agree": agree,
        "agreement": round(agree / len(rows), 4) if rows else 0.0,
        "per_rule": per_rule,
        "specs": {r: s.to_dict() for r, s in specs.items()},
        "disagreements": [r for r in rows if r["hand"] != r["gen"]],
    }


def report_lines(res: dict[str, Any]) -> str:
    """Per-rule cells, never the single number on its own (CLAUDE.md rule 5)."""
    out = [f"generated vs hand-written graders: {res['agree']}/{res['n']} "
           f"= {res['agreement']:.1%} agreement"]

    items = sorted(res["per_rule"].items(), key=lambda kv: (-kv[1]["agree"] / kv[1]["n"], kv[0]))
    perfect = [r for r, d in items if d["agree"] == d["n"]]
    divergent = [(r, d) for r, d in items if d["agree"] != d["n"]]

    if perfect:
        out.append("  perfect:    " + ", ".join(perfect))
    if divergent:
        out.append("  divergent:  " + ", ".join(
            f"{r} {d['agree']}/{d['n']}" for r, d in divergent))

    out.append("\n  spec kind chosen per rule:")
    for r, d in sorted(res["per_rule"].items()):
        out.append(f"    {r:12} {d['kind']:16} {d['agree']}/{d['n']}")
    return "\n".join(out)

