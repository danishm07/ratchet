"""Per-case × per-version state, and regression detection.

The whole point: a single aggregate number lets an improvement and a regression
cancel, which is exactly what makes the seesaw invisible. Nothing here ever
reports a score without the cells behind it.
"""

from __future__ import annotations

from typing import Any

from .cases import Case

PASS, FAIL, REGRESSION = "p", "f", "r"


def build(payload: dict, cases: list[Case]) -> dict[str, Any]:
    versions = payload["versions"]
    runs = payload["runs"]
    rows = []

    for c in cases:
        states, reasons = [], []
        prev_passed = None
        for v in versions:
            r = runs[v]["results"].get(c.id)
            passed = bool(r and r["passed"])
            if passed:
                state = PASS
            elif prev_passed:
                state = REGRESSION
            else:
                state = FAIL
            states.append(state)
            reasons.append((r or {}).get("reason", "no result"))
            prev_passed = passed
        rows.append({
            "id": c.id, "rule": c.rule, "brief": c.brief_id, "title": c.title,
            "grader": c.grader, "source_app": c.source_app,
            "from_fix": c.derived_from_fix,
            "states": states, "reasons": reasons,
        })

    per_version = []
    for i, v in enumerate(versions):
        p = sum(1 for r in rows if r["states"][i] == PASS)
        reg = [r["id"] for r in rows if r["states"][i] == REGRESSION]
        per_version.append({
            "version": v, "passing": p, "total": len(rows),
            "score": round(p / len(rows), 3) if rows else 0.0,
            "regressions": reg,
        })

    return {"versions": versions, "rows": rows, "per_version": per_version}


def summary_line(m: dict) -> str:
    parts = []
    for pv in m["per_version"]:
        flag = f"  ({len(pv['regressions'])} regressed)" if pv["regressions"] else ""
        parts.append(f"{pv['version']}: {pv['passing']}/{pv['total']} = {pv['score']:.2f}{flag}")
    return "\n".join(parts)
