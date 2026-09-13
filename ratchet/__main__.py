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
from .config import ROOT, RUNS, settings
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


def cmd_compare_graders(args) -> None:
    """Are generated graders good enough to trust? Measured, not asserted.

    The hand-written graders are the ground truth, so this runs both over the
    same documents and reports where they part company.
    """
    from . import genjudge

    path = RUNS / "latest.json"
    if not path.exists():
        raise SystemExit(
            f"no run at {path} — run `python -m ratchet run --source fixture` first, "
            "since this compares graders over the documents that run produced")
    payload = json.loads(path.read_text())
    briefs = target.load_briefs()

    res = genjudge.compare(judge.REFERENCE_RULES, payload, briefs)
    print(genjudge.report_lines(res))

    if res["disagreements"]:
        print(f"\n  {len(res['disagreements'])} disagreement(s) — hand-written verdict first:")
        for d in res["disagreements"][:args.show]:
            print(f"    {d['case']:28} {d['version']}  "
                  f"hand={'pass' if d['hand'] else 'FAIL'} gen={'pass' if d['gen'] else 'FAIL'}")
            print(f"      hand: {d['hand_reason'][:90]}")
            print(f"      gen:  {d['gen_reason'][:90]}")
        if len(res["disagreements"]) > args.show:
            print(f"    ... and {len(res['disagreements']) - args.show} more "
                  f"(raise --show to see them)")

    out = RUNS / "compare_graders.json"
    out.write_text(json.dumps(res, indent=2))
    print(f"\nllm calls: {llm_stats()}")
    print(f"full detail incl. every generated spec: {out}")


def cmd_seed(args) -> None:
    from .seed import main as seed_main
    seed_main()


def cmd_loop(args) -> None:
    """Regression -> Linear issue -> branch -> verified fix -> draft PR a human merges."""
    from . import loop
    raise SystemExit(loop.run(dry=args.dry_run, n=args.n))


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

    lp = sub.add_parser("loop",
                        help="fix one regression autonomously, up to a draft PR")
    lp.add_argument("--dry-run", action="store_true",
                    help="exercise the whole path — including candidate generation and "
                         "verification — but skip the three write calls")
    lp.add_argument("-n", type=int, default=3, help="how many candidates to propose")
    lp.set_defaults(fn=cmd_loop)

    cg = sub.add_parser("compare-graders",
                        help="generated graders vs the hand-written ones, per rule")
    cg.add_argument("--show", type=int, default=12,
                    help="how many individual disagreements to print")
    cg.set_defaults(fn=cmd_compare_graders)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
