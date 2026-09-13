"""Ratchet CLI.

    python -m ratchet run   --source fixture     # offline, for development
    python -m ratchet run                        # live: slack + linear + github
    python -m ratchet validate                   # judge agreement only
    python -m ratchet seed                       # post the corpus into the real apps
"""

from __future__ import annotations

import argparse
import json
import sys

from . import cases as case_store, extract, judge, matrix, report, runner
from .config import ROOT, settings
from .llm import stats as llm_stats
from .sources import fixture, github, linear, slack
from .sources.base import SourceError

sys.path.insert(0, str(ROOT))
from fixtures import target  # noqa: E402

LIVE = {"slack": slack.fetch, "linear": linear.fetch, "github": github.fetch}


def gather(source: str) -> tuple[list, dict]:
    if source == "fixture":
        items = fixture.fetch()
        return items, {"slack": "fixture", "linear": "fixture", "github": "fixture"}

    items, status = [], {}
    for app, fn in LIVE.items():
        try:
            got = fn()
            items += got
            status[app] = f"{len(got)} items"
        except SourceError as e:
            status[app] = f"FAILED — {e}"
    if not items:
        raise SystemExit("no items from any source; check .env and scopes")
    return items, status


def cmd_run(args) -> None:
    briefs = target.load_briefs()
    items, status = gather(args.source)
    print("sources:")
    for app, s in status.items():
        print(f"  {app:8} {s}")
    if any("FAILED" in s for s in status.values()):
        print("  (a failed source is reported, never silently skipped)")

    cs, ex_stats = extract.extract(items, briefs)
    case_store.save(cs)
    print(f"\nextraction: {ex_stats['items']} items -> {ex_stats['accepted']} checkable "
          f"-> {ex_stats['rules']} rules -> {ex_stats['cases']} cases "
          f"({ex_stats['not_checkable']} discarded, {ex_stats['parse_failed']} unparseable)")

    val = judge.validate()
    if "error" in val:
        print(f"judge validation: {val['error']}")
    else:
        print(f"judge validation: {val['agree']}/{val['n']} agreement with human labels "
              f"= {val['agreement']:.0%} on rule '{val['rule']}'")

    versions = args.versions.split(",")
    payload = runner.run_all(versions, cs, briefs)
    m = matrix.build(payload, cs)
    print("\n" + matrix.summary_line(m))

    var = None
    if args.variance:
        from . import variance as var_mod
        var = var_mod.sample(args.variance_version, cs, briefs, k=args.k)
        print("\n" + var_mod.report_line(var))

    cand = None
    if args.candidates:
        from . import candidates as cand_mod
        base = target.VERSIONS["v3"]
        cand = cand_mod.ablate(base, {
            "A: headings": ["headings"],
            "B: term match": ["termmatch"],
            "C: date format": ["date"],
        }, cs, briefs)
        print("\ncandidates (base = v3):")
        for r in cand["rows"]:
            print(f"  {r['name']:22} {r['net']:+d}  (+{r['fixes']} / -{r['breaks']})  {r['note']}")

    path = report.write(m, payload, val, ex_stats, cand)
    print(f"\nllm calls: {llm_stats()}")
    print(f"report: {path}")


def cmd_validate(args) -> None:
    print(json.dumps(judge.validate(), indent=2))


def cmd_seed(args) -> None:
    from .seed import main as seed_main
    seed_main()


def main() -> None:
    ap = argparse.ArgumentParser(prog="ratchet")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run")
    r.add_argument("--source", default="live", choices=["live", "fixture"])
    r.add_argument("--versions", default="v1,v2,v3,v4,v5")
    r.add_argument("--candidates", action="store_true")
    r.add_argument("--variance", action="store_true",
                   help="resample one version k times to separate signal from generator noise")
    r.add_argument("--variance-version", default="v4")
    r.add_argument("--k", type=int, default=3)
    r.set_defaults(fn=cmd_run)

    v = sub.add_parser("validate"); v.set_defaults(fn=cmd_validate)
    s = sub.add_parser("seed"); s.set_defaults(fn=cmd_seed)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
