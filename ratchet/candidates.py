"""Run candidate changes independently, then their combinations.

The serial habit — fix, break, fix, break — never reveals that the best result
was a combination you skipped past. Each candidate is evaluated against the full
suite on its own, and then the combinations are evaluated too, because effects
interact and nothing in the individual profiles predicts that.
"""

from __future__ import annotations

import concurrent.futures as cf
import itertools
import sys

from . import judge
from .cases import Case
from .config import ROOT

sys.path.insert(0, str(ROOT))
from fixtures import target  # noqa: E402


def _score(rules: list[str], cases: list[Case], briefs: list[dict], workers: int = 6) -> set[str]:
    """Returns the set of case ids that pass under this rule set."""
    from .llm import complete
    by_id = {b["id"]: b for b in briefs}

    def gen(b):
        return b["id"], complete(target.prompt_for("custom", b, rules=rules))

    docs = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for bid, text in ex.map(gen, briefs):
            docs[bid] = text

    def one(c: Case):
        return c.id, judge.grade(c, docs[c.brief_id], by_id[c.brief_id]).passed

    passing = set()
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for cid, ok in ex.map(one, cases):
            if ok:
                passing.add(cid)
    return passing


def ablate(base_rules: list[str], candidates: dict[str, list[str]],
           cases: list[Case], briefs: list[dict]) -> dict:
    """base_rules plus each candidate's added rules, alone and in combination."""
    base = _score(base_rules, cases, briefs)
    rows = []
    scores: dict[str, set[str]] = {}

    for name, add in candidates.items():
        s = _score(sorted(set(base_rules) | set(add)), cases, briefs)
        scores[name] = s
        rows.append({
            "name": name,
            "fixes": len(s - base),
            "breaks": len(base - s),
            "net": len(s) - len(base),
            "note": "added: " + ", ".join(add),
        })

    for combo in itertools.combinations(candidates, 2):
        add = sorted(set().union(*[candidates[c] for c in combo]))
        s = _score(sorted(set(base_rules) | set(add)), cases, briefs)
        predicted = len(set().union(*[scores[c] - base for c in combo])) - \
            len(set().union(*[base - scores[c] for c in combo]))
        actual = len(s) - len(base)
        note = "as predicted from the parts" if actual >= predicted else \
            f"INTERACTION: predicted {predicted:+d}, measured {actual:+d}"
        rows.append({
            "name": " + ".join(combo),
            "fixes": len(s - base),
            "breaks": len(base - s),
            "net": actual,
            "note": note,
        })

    rows.sort(key=lambda r: -r["net"])
    return {"base_passing": len(base), "total_cases": len(cases), "rows": rows}
