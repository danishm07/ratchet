"""Graders, and the validation that makes their output worth believing.

Two principles, both from CLAUDE.md:

1. Deterministic graders win. If a criterion can be checked with a parse, a
   regex or arithmetic, do that — it is cheaper, faster, and has no agreement
   problem. Only genuinely subjective criteria get an LLM judge.

2. An unvalidated judge is a rubber ruler. `validate()` measures agreement with
   human labels before any suite number is believed. If agreement is poor the
   judge gets fixed, not the system under test.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from typing import Any, Callable

from .cases import Case
from .config import FIXTURES
from .llm import complete_json

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]
WORD_NUM = {"ten": 10, "twenty": 20, "twenty-five": 25, "thirty": 30, "forty": 40,
            "fifty": 50, "sixty": 60, "seventy": 70, "seventy-five": 75,
            "eighty": 80, "ninety": 90, "one hundred": 100}
NUM_WORD = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
SYMBOL = {"USD": "$", "GBP": "£", "EUR": "€"}


@dataclass
class Verdict:
    passed: bool
    reason: str
    quote: str = ""
    grader: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _money(text: str) -> list[int]:
    return [int(m.replace(",", "")) for m in re.findall(r"[$£€]\s?([\d,]{4,})", text)]


# ----------------------------------------------------------------- graders

def g_date(out: str, brief: dict) -> Verdict:
    bad = re.findall(r"\b(J[au]me|Janurary|Feburary|Agust|Setember|Ocotber|Deciembre|Jully)\b", out, re.I)
    if bad:
        return Verdict(False, f"misspelled month: {bad[0]}", bad[0])
    good = re.findall(r"\b\d{1,2}\s+(" + "|".join(MONTHS) + r")\s+\d{4}\b", out)
    other = re.findall(r"\b(?:" + "|".join(MONTHS) + r")\s+\d{1,2},\s*\d{4}\b", out)
    if other and not good:
        return Verdict(False, f"wrong date format: {other[0]!r}, expected '14 June 2026'", other[0])
    if not good:
        return Verdict(False, "no date in the required '14 June 2026' form found")
    return Verdict(True, f"{len(good)} date(s) correctly formatted", good[0])


def g_totals(out: str, brief: dict) -> Verdict:
    want = sum(p["fee"] for p in brief["phases"])
    m = re.search(r"total[^\n\d]{0,40}[$£€]?\s?([\d,]{4,})", out, re.I)
    if not m:
        return Verdict(False, "no total line found in the fee table")
    got = int(m.group(1).replace(",", ""))
    if got != want:
        return Verdict(False, f"total {got:,} but phases sum to {want:,}", m.group(0).strip())
    return Verdict(True, f"total {got:,} equals the sum of phases", m.group(0).strip())


def _spelled_number(words: str) -> str | None:
    """Resolve the number word immediately before 'percent'.

    The naive version captured the whole run of preceding words ("a deposit of
    fifty"), failed to find it in the table, and passed silently — a false
    negative that inflates the score. Try the last two tokens ("one hundred")
    then the last one ("twenty-five").
    """
    toks = words.strip().lower().split()
    for cand in (" ".join(toks[-2:]), toks[-1] if toks else ""):
        if cand in WORD_NUM:
            return cand
    return None


def g_percent(out: str, brief: dict) -> Verdict:
    hits = re.findall(r"([a-z\- ]+?)\s+percent\s*\(\s*(\d{1,3})\s*%\s*\)", out, re.I)
    if not hits:
        return Verdict(False, "no 'words percent (N%)' construction found")
    checked = 0
    for words, num in hits:
        w = _spelled_number(words)
        if w is None:
            continue
        checked += 1
        if WORD_NUM[w] != int(num):
            return Verdict(False, f"'{w} percent ({num}%)' — words and numeral disagree",
                           f"{w} percent ({num}%)")
    if checked == 0:
        return Verdict(True, "no recognisable spelled number to check against the numeral")
    return Verdict(True, f"{checked} spelled percentage(s) match their numerals",
                   f"{hits[0][0].strip().split()[-1]} percent ({hits[0][1]}%)")


HEAD_RE = re.compile(r"^\s*(?:#{1,4}\s*)?(?:\*\*|__)?\s*(\d)\.\s+[A-Z]", re.M)


def g_headings(out: str, brief: dict) -> Verdict:
    nums = HEAD_RE.findall(out)
    if len(nums) < 4:
        return Verdict(False, f"only {len(nums)} numbered headings found, expected at least 4")
    return Verdict(True, f"{len(nums)} numbered headings present")


def g_daterange(out: str, brief: dict) -> Verdict:
    found = re.findall(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})\b", out)
    if len(found) < 2:
        return Verdict(True, "fewer than two dates; nothing to order")
    def key(t): return (int(t[2]), MONTHS.index(t[1]), int(t[0]))
    if key(found[1]) < key(found[0]):
        return Verdict(False, f"end date {' '.join(found[1])} precedes start {' '.join(found[0])}",
                       " ".join(found[1]))
    return Verdict(True, "dates are in order")


def g_currency(out: str, brief: dict) -> Verdict:
    syms = set(re.findall(r"[$£€]", out))
    if len(syms) > 1:
        return Verdict(False, f"mixed currency symbols: {' '.join(sorted(syms))}")
    want = SYMBOL.get(brief["currency"], "$")
    if syms and want not in syms:
        return Verdict(False, f"currency {syms.pop()} but the brief specifies {brief['currency']}")
    return Verdict(True, f"single currency symbol {want}")


def g_termmatch(out: str, brief: dict) -> Verdict:
    want = brief["engagement_length_months"]
    m = re.search(r"(?:term|period|duration)[^\n.]{0,60}?(\w+)\s*\((\d{1,2})\)\s*months?", out, re.I)
    if m:
        got = int(m.group(2))
    else:
        m = re.search(r"(\d{1,2})[- ]month", out, re.I)
        if not m:
            m2 = re.search(r"\b(" + "|".join(NUM_WORD) + r")[- ]month", out, re.I)
            if not m2:
                return Verdict(False, "no term length stated in the body")
            got = NUM_WORD[m2.group(1).lower()]
            m = m2
        else:
            got = int(m.group(1))
    if got != want:
        return Verdict(False, f"body states {got} months, brief quotes {want}", m.group(0))
    return Verdict(True, f"term of {got} months matches the brief", m.group(0))


def g_section(name: str) -> Callable[[str, dict], Verdict]:
    def grader(out: str, brief: dict) -> Verdict:
        pat = rf"^\s*(?:#{{1,4}}\s*)?(?:\*\*|__)?\s*(?:\d\.\s*)?{name}\b"
        if re.search(pat, out, re.I | re.M):
            return Verdict(True, f"{name} section present")
        return Verdict(False, f"no {name} section")
    return grader


# --------------------------------------------------- the one LLM-judged rule

LEGALNAME_PROMPT = """Decide whether the DOCUMENT correctly handled the client's legal entity name.

The brief did NOT supply a legal entity name. The correct behaviour is to leave a
visible placeholder (for example [CLIENT LEGAL NAME]) rather than invent one.
Using the client's short trading name alone is acceptable. Inventing a legal
suffix the brief never supplied — "Ltd", "LLC", "Inc.", "GmbH", "Holdings" — is not.

CLIENT SHORT NAME: {client}

DOCUMENT:
{out}

Return ONLY JSON: {{"passed": true|false, "reason": "<one sentence>", "quote": "<the exact phrase that decides it, or empty>"}}"""


def g_legalname(out: str, brief: dict) -> Verdict:
    if brief.get("client_legal_name"):
        return Verdict(True, "brief supplied a legal name; nothing to invent")
    data = complete_json(LEGALNAME_PROMPT.format(client=brief["client"], out=out[:3000]))
    if not isinstance(data, dict) or "passed" not in data:
        return Verdict(False, "judge returned no parseable verdict", grader="llm")
    return Verdict(bool(data["passed"]), str(data.get("reason", ""))[:200],
                   str(data.get("quote", ""))[:160], grader="llm")


GRADERS: dict[str, Callable[[str, dict], Verdict]] = {
    "date": g_date,
    "totals": g_totals,
    "percent": g_percent,
    "headings": g_headings,
    "daterange": g_daterange,
    "currency": g_currency,
    "termmatch": g_termmatch,
    "assume": g_section("Assumptions"),
    "excl": g_section("Exclusions"),
    "legalname": g_legalname,
}

LLM_RULES = {"legalname"}

# The ten rules these graders were written for, with the expectation each one
# encodes. This is the reference set: `compare-graders` generates a grader from
# each expectation and measures it against the hand-written one above.
#
# It lives here rather than in extract.py because extraction no longer has a menu
# to classify into — these are a property of the graders, not of extraction.
REFERENCE_RULES: dict[str, str] = {
    "date":      "every date is written in the form '14 June 2026', with no abbreviated or misspelled month",
    "totals":    "the Total stated in the fee table equals the arithmetic sum of the phase fees",
    "percent":   "a percentage written in words agrees with the numeral beside it, as in 'fifty percent (50%)'",
    "headings":  "the document uses a numbered heading hierarchy, with at least four numbered headings",
    "legalname": "when the brief supplies no client legal entity name, a placeholder is left rather than a legal name being invented",
    "daterange": "the engagement end date falls after the start date",
    "assume":    "the document contains an Assumptions section",
    "currency":  "a single currency symbol is used throughout, matching the currency named in the brief",
    "termmatch": "the term length stated in the body matches the engagement length quoted in the brief",
    "excl":      "the document contains an Exclusions section",
}


def reference_cases(briefs: list[dict]) -> list[Case]:
    """One case per reference rule per brief — the suite that actually gets scored.

    Built here rather than read from disk so the number is reproducible from one
    command: extraction names its own rules now, so cases.json holds different
    slugs on every corpus, while the scored grid must stay fixed.
    """
    return [
        Case(id=f"{rule}::{b['id']}", rule=rule, title=rule, expectation=exp,
             brief_id=b["id"], grader="llm" if rule in LLM_RULES else "deterministic",
             source_app="reference", source_id=rule, source_text=exp)
        for rule, exp in sorted(REFERENCE_RULES.items())
        for b in briefs
    ]


def grade(case: Case, output: str, brief: dict) -> Verdict:
    """The one entry point for grading, so runner.py stays pure orchestration.

    **Only hand-written graders score a suite.** These are the graders whose
    agreement with human labels has been measured; a generated one has not
    earned that job and does not get it here. `genjudge` is reachable from
    `compare-graders` alone, where its output is measured against these rather
    than believed.

    An unknown rule raises. It does not quietly score zero and it does not
    quietly score a pass: a case with no grader is missing data, which
    CLAUDE.md rule 6 makes a distinct state from a failing case.
    """
    fn = GRADERS.get(case.rule)
    if fn is None:
        raise RuntimeError(
            f"judge: no grader registered for rule {case.rule!r} (case {case.id!r}). "
            f"Known rules: {', '.join(sorted(GRADERS))}. "
            f"Generated graders are not a scoring path — see `ratchet compare-graders`.")
    return fn(output, brief)


# ------------------------------------------------------------- validation

def validate(labels_path=None) -> dict[str, Any]:
    """Measure agreement between the LLM judge and human labels.

    Deterministic graders are excluded — they are not judgements. Only the
    LLM-judged rule is measured, because that is the only place a rubber ruler
    can hide.
    """
    labels_path = labels_path or (FIXTURES / "judge_labels.json")
    if not labels_path.exists():
        return {"error": f"no labels at {labels_path}"}
    rows = json.loads(labels_path.read_text())
    agree = 0
    disagreements = []
    for r in rows:
        v = g_legalname(r["output"], r["brief"])
        if v.passed == r["human"]:
            agree += 1
        else:
            disagreements.append({"id": r["id"], "human": r["human"],
                                  "judge": v.passed, "reason": v.reason})
    n = len(rows)
    return {
        "rule": "legalname",
        "n": n,
        "agree": agree,
        "agreement": round(agree / n, 3) if n else 0.0,
        "disagreements": disagreements,
    }
