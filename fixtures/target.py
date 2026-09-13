"""The system under test: a fictional engagement-letter generator.

Everything here is invented. "Northwind Advisory" is not a real firm and the
briefs are synthetic.

Five versions of the generator's prompt. Each is a plausible edit someone made
on a Monday to fix a complaint — and each, like real prompt edits, quietly drops
a rule that a previous version had, because a section got rewritten. That is how
regressions actually happen, and it means the regressions Ratchet finds here are
genuine emergent behaviour, not staged.

Rule keys, tracked across versions:
  date      dates written as "14 June 2026"
  totals    phase fees must sum to the stated total
  percent   a spelled-out percentage must match its numeral
  headings  numbered heading hierarchy
  legalname placeholder when the brief gives no legal entity
  daterange end date must be after start date
  assume    an Assumptions section must be present
  currency  one currency symbol throughout
  termmatch stated term length matches the quoted length
  excl      explicit exclusions list
"""

from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).parent

RULES = {
    "date":      'Write every date in the form "14 June 2026". Never abbreviate or misspell a month.',
    "totals":    "In the fee table, the stated Total MUST equal the arithmetic sum of the phase fees. Add them.",
    "percent":   'When a percentage is written in words followed by a numeral, the two MUST agree — "fifty percent (50%)".',
    "headings":  "Use a numbered heading hierarchy: 1. Scope of Services, 2. Our Approach, 3. Fees, 4. Timeline, 5. Assumptions, 6. Exclusions.",
    "legalname": "If the brief does not supply the client's legal entity name, write [CLIENT LEGAL NAME] as a placeholder. Never invent one.",
    "daterange": "The engagement end date must fall after the start date.",
    "assume":    "Always include an Assumptions section with at least two assumptions.",
    "currency":  "Use a single currency symbol throughout, taken from the brief.",
    "termmatch": "The term length stated in the body must match the engagement length quoted in the brief.",
    "excl":      "Always include an Exclusions section listing what is out of scope.",
}

# Each version's rule set. Note what leaves as well as what arrives.
VERSIONS: dict[str, list[str]] = {
    # baseline: structure rules only
    "v1": ["headings", "assume", "excl", "totals", "daterange", "termmatch"],
    # "fix the date typos and stop inventing client names"
    # — the fee section was rewritten in the process and lost the totals rule
    "v2": ["headings", "assume", "excl", "daterange", "termmatch", "date", "legalname", "percent"],
    # "the totals are wrong again, and currencies are mixed"
    # — template restructure dropped numbered headings and the term-match rule
    "v3": ["assume", "excl", "daterange", "date", "legalname", "percent", "totals", "currency"],
    # "headings and term length are broken"
    # — section 3 was rewritten and the date rule went with it
    "v4": ["headings", "assume", "excl", "daterange", "legalname", "percent",
           "totals", "currency", "termmatch"],
    # consolidated
    "v5": list(RULES.keys()),
}

SYSTEM = """You are a document generator for Northwind Advisory, a fictional consulting firm.
Write a short engagement letter from the brief below. Six sections maximum, terse.
Output the letter only — no preamble, no commentary."""


def prompt_for(version: str, brief: dict, rules: list[str] | None = None) -> str:
    rules = rules if rules is not None else VERSIONS[version]
    rule_text = "\n".join(f"- {RULES[r]}" for r in rules) or "- (no additional rules)"
    return (
        f"{SYSTEM}\n\nRULES:\n{rule_text}\n\nBRIEF:\n{json.dumps(brief, indent=2)}\n"
    )


def load_briefs() -> list[dict]:
    return json.loads((HERE / "briefs.json").read_text())
