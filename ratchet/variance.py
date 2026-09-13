"""How much of a flipped case is the change, and how much is the generator?

A single sample per (version, brief) cannot separate "this edit caused the
regression" from "the generator is unstable on this case". Ratchet quantifies
that instead of hand-waving it: the same version is sampled k times and the
per-case flip rate is reported. A case that flips between identical runs is
noise, and a change that moves only noisy cases has not been shown to do
anything.

Method: the CLI backend exposes no temperature, so each repeat appends a
distinct trailing marker to the prompt, which changes the sampling path. The
marker is inert with respect to the task. With the OpenRouter backend this
would be a temperature setting instead; the measurement is the same.
"""

from __future__ import annotations

import concurrent.futures as cf
import sys

from . import judge
from .cases import Case
from .config import ROOT
from .llm import complete

sys.path.insert(0, str(ROOT))
from fixtures import target  # noqa: E402


def sample(version: str, cases: list[Case], briefs: list[dict], k: int = 3,
           workers: int = 6) -> dict:
    by_id = {b["id"]: b for b in briefs}
    per_case_runs: dict[str, list[bool]] = {c.id: [] for c in cases}

    for i in range(k):
        marker = "" if i == 0 else f"\n\n<!-- sample {i} -->"

        def gen(b):
            return b["id"], complete(target.prompt_for(version, b) + marker)

        docs = {}
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            for bid, text in ex.map(gen, briefs):
                docs[bid] = text

        def one(c: Case):
            return c.id, judge.grade(c, docs[c.brief_id], by_id[c.brief_id]).passed

        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            for cid, ok in ex.map(one, cases):
                per_case_runs[cid].append(ok)

    stable, unstable = [], []
    for cid, runs in per_case_runs.items():
        (stable if len(set(runs)) == 1 else unstable).append(cid)

    by_rule: dict[str, dict[str, int]] = {}
    for c in cases:
        r = by_rule.setdefault(c.rule, {"stable": 0, "unstable": 0})
        r["stable" if len(set(per_case_runs[c.id])) == 1 else "unstable"] += 1

    return {
        "version": version,
        "k": k,
        "n_cases": len(cases),
        "stable": len(stable),
        "unstable": len(unstable),
        "flip_rate": round(len(unstable) / len(cases), 3) if cases else 0.0,
        "unstable_ids": sorted(unstable),
        "by_rule": by_rule,
        "runs": {cid: runs for cid, runs in per_case_runs.items()},
    }


def report_line(v: dict) -> str:
    noisy = [r for r, c in v["by_rule"].items() if c["unstable"]]
    out = (f"variance on {v['version']} (k={v['k']}): {v['stable']}/{v['n_cases']} cases stable, "
           f"flip rate {v['flip_rate']:.0%}")
    if noisy:
        out += "\n  unstable rules: " + ", ".join(
            f"{r} ({v['by_rule'][r]['unstable']}/{v['by_rule'][r]['stable'] + v['by_rule'][r]['unstable']})"
            for r in sorted(noisy))
    return out
