"""Run every case against one or more versions of the system under test."""

from __future__ import annotations

import concurrent.futures as cf
import json
import sys
import time
from typing import Callable

from . import judge, progress
from .cases import Case, load as load_cases
from .config import RUNS
from .llm import complete, stats as llm_stats

sys.path.insert(0, str((RUNS.parent.parent / "fixtures").parent))
from fixtures import target  # noqa: E402


def generate(version: str, briefs: list[dict], workers: int = 6) -> dict[str, str]:
    """Produce (and cache) one document per brief for this version."""
    def one(b):
        return b["id"], complete(target.prompt_for(version, b))
    out = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for bid, text in progress.track(ex.map(one, briefs), len(briefs),
                                        f"generating {version}", "documents",
                                        done=f"generated {version}"):
            out[bid] = text
    return out


def run_version(version: str, cases: list[Case], briefs: list[dict],
                workers: int = 6) -> dict:
    by_id = {b["id"]: b for b in briefs}
    docs = generate(version, briefs, workers)

    def one(c: Case):
        v = judge.grade(c, docs[c.brief_id], by_id[c.brief_id])
        return c.id, v

    results = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for cid, v in progress.track(ex.map(one, cases), len(cases),
                                     f"grading {version}", "cases",
                                     done=f"graded {version}"):
            results[cid] = v.to_dict()

    return {"version": version, "results": results, "docs": docs}


def run_all(versions: list[str], cases: list[Case], briefs: list[dict],
            on_version: Callable[[dict, str, int, int], None] | None = None) -> dict:
    """Run every version. `on_version` is called with the payload-so-far after
    each one, so a caller can render partial results while the rest still runs.

    The callback takes the payload rather than runner doing anything with it —
    runner stays orchestration and never learns what a report is.
    """
    t0 = time.time()
    runs: dict[str, dict] = {}
    for i, v in enumerate(versions, 1):
        runs[v] = run_version(v, cases, briefs)
        if on_version is not None and i < len(versions):
            on_version({"versions": versions[:i], "runs": runs,
                        "seconds": round(time.time() - t0, 1), "llm": llm_stats()},
                       v, i, len(versions))
    payload = {
        "versions": versions,
        "runs": runs,
        "seconds": round(time.time() - t0, 1),
        "llm": llm_stats(),
    }
    (RUNS / "latest.json").write_text(json.dumps(payload, indent=2))
    return payload
