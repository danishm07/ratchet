"""Close the loop: one regression in, one pull request out, a human merges it.

This is the shape every shipped coding agent converges on — GitHub's Copilot
coding agent, Cursor's background agents, Devin. Fully autonomous up to the pull
request, and a person gates the merge. Nothing here merges, force-pushes, or
writes to the default branch, and `--dry-run` exercises the entire path including
candidate generation and verification while skipping only the three write calls.

    regression detected
      -> Linear issue                  (write)
      -> branch off the default branch (write)
      -> propose up to 3 candidate fixes
      -> run the FULL suite for each
      -> accept only if FAIL_TO_PASS and PASS_TO_PASS both hold
      -> draft PR carrying the before/after matrix   (write)
      -> if nothing passes: comment the attempts on the issue, delete the branch,
         exit non-zero

**The verification step is the part that matters.** SWE-bench's split is adopted
here by name, because it is the thing most agents do worst: they run the suite,
see green, and ship. Green is not the bar.

    FAIL_TO_PASS   the regressed case must now pass
    PASS_TO_PASS   every case that passed before must still pass

A candidate that fixes the target and breaks anything else is rejected, and the
rejection records exactly which cases it broke. Top agents resolve 75-90% on
curated benchmarks and real tickets are harder, so giving up is a normal path
through this code, not an exception — and a clean give-up that says what it tried
is worth more than a PR somebody has to revert.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from typing import Any

import httpx

from . import candidates as cand_mod, matrix
from .cases import Case, load as load_cases
from .config import ROOT, RUNS, settings
from .llm import complete_json
from .sources.base import SourceError

sys.path.insert(0, str(ROOT))
from fixtures import target  # noqa: E402

GITHUB = "https://api.github.com"
LINEAR = "https://api.linear.app/graphql"

PROTECTED = {"main", "master", "trunk", "develop"}


# --------------------------------------------------------------------- detect

@dataclass
class Regression:
    """A case that passed in one version and fails in the next."""
    case_id: str
    rule: str
    brief_id: str
    title: str
    version: str          # where it broke
    prev_version: str     # where it last passed
    reason: str
    quote: str = ""

    @property
    def short_id(self) -> str:
        return self.brief_id[:8]

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items()}


def detect(payload: dict, cases: list[Case]) -> Regression | None:
    """The first case whose state is 'r' — passed before, fails now.

    Deliberately the *first* rather than the worst: the loop fixes one thing and
    opens one reviewable PR. A batch of fixes is a batch of reverts.
    """
    m = matrix.build(payload, cases)
    by_id = {c.id: c for c in cases}
    versions = m["versions"]

    for row in m["rows"]:
        for i, state in enumerate(row["states"]):
            if state != matrix.REGRESSION:
                continue
            c = by_id[row["id"]]
            v = versions[i]
            verdict = payload["runs"][v]["results"].get(c.id, {})
            return Regression(
                case_id=c.id, rule=c.rule, brief_id=c.brief_id, title=c.title,
                version=v, prev_version=versions[i - 1],
                reason=verdict.get("reason", row["reasons"][i]),
                quote=verdict.get("quote", ""),
            )
    return None


# ------------------------------------------------------------------- propose

PROPOSE_PROMPT = """A regression test is failing against a document generator whose behaviour is
controlled entirely by which rules are included in its prompt.

THE FAILURE
  rule broken:   {rule}
  what it wants: {title}
  the grader's reason for failing it: {reason}
  the offending text from the document: {quote}
  brief this happened on: {brief_id}
  it passed at {prev_version} and fails at {version}

RULES CURRENTLY IN THE PROMPT AT {version}
{current}

EVERY RULE AVAILABLE
{available}

Propose exactly 3 DISTINCT candidate fixes. Each is an edit to the rule list:
rules to add, rules to remove, or both. They must be genuinely different
approaches, not three phrasings of one idea — the point is to find out which one
survives the full suite, and identical candidates tell us nothing.

Use ONLY rule keys from the list above. Adding a rule that is already present is
a no-op and wastes a candidate.

Return ONLY JSON:
{{"candidates": [
  {{"add": ["<rule key>"], "remove": [], "rationale": "<one line: why this would fix it>"}},
  {{"add": [], "remove": ["<rule key>"], "rationale": "<one line>"}},
  {{"add": ["<rule key>"], "remove": ["<rule key>"], "rationale": "<one line>"}}
]}}"""


@dataclass
class Candidate:
    name: str
    add: list[str]
    remove: list[str]
    rationale: str
    rules: list[str] = field(default_factory=list)
    # filled in by verify()
    fail_to_pass: bool | None = None
    pass_to_pass: bool | None = None
    broke: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)
    accepted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def verdict_line(self) -> str:
        if self.accepted:
            return "ACCEPTED"
        bits = []
        if self.fail_to_pass is False:
            bits.append("did not fix the target case")
        if self.broke:
            bits.append(f"broke {len(self.broke)} passing case(s)")
        return "REJECTED — " + (", ".join(bits) or "no effect")


def propose(reg: Regression, n: int = 3) -> list[Candidate]:
    """Ask for n distinct edits to the rule list. Cached like every other call."""
    current = target.VERSIONS[reg.version]
    data = complete_json(PROPOSE_PROMPT.format(
        rule=reg.rule, title=reg.title, reason=reg.reason,
        quote=reg.quote or "(none recorded)", brief_id=reg.brief_id,
        version=reg.version, prev_version=reg.prev_version,
        current="\n".join(f"  - {r}: {target.RULES[r]}" for r in current),
        available="\n".join(f"  - {k}: {v}" for k, v in target.RULES.items()),
    ))
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
        raise RuntimeError("loop: model returned no parseable candidate list")

    out: list[Candidate] = []
    for i, c in enumerate(data["candidates"][:n], 1):
        if not isinstance(c, dict):
            continue
        add = [r for r in c.get("add", []) if r in target.RULES]
        remove = [r for r in c.get("remove", []) if r in target.RULES]
        rules = sorted((set(current) | set(add)) - set(remove))
        if not rules:
            continue  # an empty prompt is not a candidate fix
        out.append(Candidate(
            name=f"candidate-{i}", add=add, remove=remove,
            rationale=str(c.get("rationale", ""))[:200], rules=rules))
    if not out:
        raise RuntimeError("loop: no usable candidates after validation against target.RULES")
    return out


# -------------------------------------------------------------------- verify

def verify(cands: list[Candidate], reg: Regression, cases: list[Case],
           briefs: list[dict], payload: dict) -> list[Candidate]:
    """SWE-bench's split, applied per case.

    The baseline is the set of cases passing at the broken version. A candidate
    is accepted only if it moves the regressed case into the passing set AND
    loses none of the baseline. Anything else is rejected with the specific
    cases it broke, because "the suite went green" is not the same claim as
    "nothing else changed".
    """
    baseline = {cid for cid, r in payload["runs"][reg.version]["results"].items()
                if r.get("passed")}

    for c in cands:
        got = cand_mod.passing_set(c.rules, cases, briefs)
        c.fail_to_pass = reg.case_id in got
        c.broke = sorted(baseline - got)
        c.fixed = sorted(got - baseline)
        c.pass_to_pass = not c.broke
        c.accepted = bool(c.fail_to_pass and c.pass_to_pass)
    return cands


# ------------------------------------------------------------- external calls

def _gh(method: str, path: str, payload: dict | None = None) -> dict:
    if not settings.github_token or not settings.github_repo:
        raise SourceError("github: GITHUB_TOKEN or GITHUB_REPO missing")
    resp = httpx.request(
        method, f"{GITHUB}{path}",
        headers={"Authorization": f"Bearer {settings.github_token}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"},
        json=payload, timeout=30,
    )
    if resp.status_code >= 300:
        raise SourceError(f"github {method} {path}: {resp.status_code} {resp.text[:200]}")
    return resp.json() if resp.content else {}


def _linear(query: str, variables: dict) -> dict:
    if not settings.linear_key:
        raise SourceError("linear: LINEAR_API_KEY missing")
    resp = httpx.post(LINEAR, headers={"Authorization": settings.linear_key},
                      json={"query": query, "variables": variables}, timeout=30)
    if resp.status_code != 200:
        raise SourceError(f"linear: HTTP {resp.status_code} {resp.text[:200]}")
    body = resp.json()
    if "errors" in body:
        raise SourceError(f"linear: {body['errors'][:1]}")
    return body["data"]


ISSUE_CREATE = """
mutation Create($t: String!, $d: String!, $team: String!) {
  issueCreate(input: {title: $t, description: $d, teamId: $team}) {
    success issue { id identifier url }
  }
}"""

COMMENT_CREATE = """
mutation Comment($id: String!, $body: String!) {
  commentCreate(input: {issueId: $id, body: $body}) { success }
}"""


def create_issue(reg: Regression, dry: bool) -> dict[str, str]:
    title = f"[ratchet] {reg.rule} regressed at {reg.version} on brief '{reg.brief_id}'"
    body = (
        f"**Case** `{reg.case_id}`\n\n"
        f"**What the rule wants:** {reg.title}\n\n"
        f"**Grader's reason for failing it:** {reg.reason}\n\n"
        f"**Offending text:** {reg.quote or '_(none recorded)_'}\n\n"
        f"Passed at `{reg.prev_version}`, fails at `{reg.version}`.\n\n"
        f"Filed automatically by `python -m ratchet loop`."
    )
    if dry:
        return {"identifier": "DRY-000", "url": "(dry-run: no issue created)",
                "id": "", "title": title, "body": body}

    team = _linear("{ teams(first: 1) { nodes { id } } }", {})["teams"]["nodes"]
    if not team:
        raise SourceError("linear: no team found — create one in the app first")
    data = _linear(ISSUE_CREATE, {"t": title, "d": body, "team": team[0]["id"]})
    issue = data["issueCreate"]["issue"]
    return {"identifier": issue["identifier"], "url": issue["url"],
            "id": issue["id"], "title": title, "body": body}


def create_branch(reg: Regression, dry: bool) -> dict[str, str]:
    name = f"ratchet/fix-{reg.rule}-{reg.short_id}".replace("_", "-")
    if name.rsplit("/", 1)[-1] in PROTECTED or name in PROTECTED:
        raise RuntimeError(f"loop: refusing to write to protected branch {name!r}")
    if dry:
        return {"name": name, "base": "(dry-run)", "sha": "0" * 40}

    base = _gh("GET", f"/repos/{settings.github_repo}")["default_branch"]
    if base in (name,):
        raise RuntimeError("loop: branch name collides with the default branch")
    sha = _gh("GET", f"/repos/{settings.github_repo}/git/ref/heads/{base}")["object"]["sha"]
    _gh("POST", f"/repos/{settings.github_repo}/git/refs",
        {"ref": f"refs/heads/{name}", "sha": sha})
    return {"name": name, "base": base, "sha": sha}


def commit_candidate(branch: str, c: Candidate, reg: Regression, dry: bool) -> str:
    """Each attempt lands as its own file, so the PR shows what was tried and rejected."""
    import base64

    path = f"candidates/{reg.rule}-{reg.short_id}/{c.name}.md"
    content = (
        f"# {c.name}\n\n"
        f"{c.rationale}\n\n"
        f"- add: {', '.join(c.add) or '(none)'}\n"
        f"- remove: {', '.join(c.remove) or '(none)'}\n"
        f"- resulting rule list: {', '.join(c.rules)}\n\n"
        f"## Verification\n\n"
        f"- FAIL_TO_PASS ({reg.case_id}): {'PASS' if c.fail_to_pass else 'FAIL'}\n"
        f"- PASS_TO_PASS: {'PASS' if c.pass_to_pass else f'FAIL — broke {len(c.broke)}'}\n"
        f"- also fixed: {', '.join(c.fixed) or '(none)'}\n"
        f"- broke: {', '.join(c.broke) or '(none)'}\n\n"
        f"**{c.verdict_line}**\n"
    )
    if dry:
        return path
    _gh("PUT", f"/repos/{settings.github_repo}/contents/{path}", {
        "message": f"ratchet: {c.name} for {reg.rule} — {c.verdict_line}",
        "content": base64.b64encode(content.encode()).decode(),
        "branch": branch,
    })
    return path


def pr_body(reg: Regression, issue: dict, cands: list[Candidate],
            chosen: Candidate, baseline: set[str], after: set[str]) -> str:
    """Everything a reviewer needs, so they never have to open another tab."""
    rows = [
        "| candidate | add | remove | FAIL_TO_PASS | PASS_TO_PASS | fixed | broke |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in cands:
        rows.append(
            f"| {c.name}{' **←chosen**' if c is chosen else ''} "
            f"| {', '.join(c.add) or '—'} | {', '.join(c.remove) or '—'} "
            f"| {'✅' if c.fail_to_pass else '❌'} "
            f"| {'✅' if c.pass_to_pass else f'❌ broke {len(c.broke)}'} "
            f"| {len(c.fixed)} | {len(c.broke)} |")

    gained = sorted(after - baseline)
    lost = sorted(baseline - after)
    return f"""## The failure that started this

`{reg.case_id}` passed at `{reg.prev_version}` and fails at `{reg.version}`.

> {reg.reason}

{f'Offending text: `{reg.quote}`' if reg.quote else ''}

Linear issue: {issue['url']}

## Candidates tried

{chr(10).join(rows)}

## Why `{chosen.name}`

{chosen.rationale}

It is the only candidate for which **both** SWE-bench conditions hold: the
regressed case passes (FAIL_TO_PASS) and no case that passed before now fails
(PASS_TO_PASS). Candidates that fixed the target while breaking something else
were rejected — that trade is the exact failure this repo exists to make visible.

## Before / after

| | passing |
|---|---|
| `{reg.version}` (before) | {len(baseline)} |
| with `{chosen.name}` | {len(after)} |

- newly passing: {', '.join(f'`{c}`' for c in gained) or '_none_'}
- newly failing: {', '.join(f'`{c}`' for c in lost) or '_none_'}

---
Opened as a **draft** by `python -m ratchet loop`. Nothing here is auto-merged.
A human reviews and merges, or closes it.
"""


def open_pr(reg: Regression, branch: dict, body: str, dry: bool) -> str:
    title = f"ratchet: fix {reg.rule} regression at {reg.version}"
    if dry:
        return "(dry-run: no PR opened)"
    pr = _gh("POST", f"/repos/{settings.github_repo}/pulls", {
        "title": title, "head": branch["name"], "base": branch["base"],
        "body": body, "draft": True,
    })
    return pr["html_url"]


def comment_failure(issue: dict, cands: list[Candidate], dry: bool) -> None:
    lines = ["`ratchet loop` tried 3 candidates and **none** satisfied both "
             "FAIL_TO_PASS and PASS_TO_PASS. No PR was opened.\n"]
    for c in cands:
        lines.append(f"**{c.name}** — {c.rationale}")
        lines.append(f"- add: {', '.join(c.add) or '(none)'} · "
                     f"remove: {', '.join(c.remove) or '(none)'}")
        lines.append(f"- {c.verdict_line}")
        if c.broke:
            lines.append(f"- broke: {', '.join(f'`{b}`' for b in c.broke[:10])}"
                         + (f" _(+{len(c.broke) - 10} more)_" if len(c.broke) > 10 else ""))
        lines.append("")
    body = "\n".join(lines)
    if dry:
        print("\n--- would comment on the Linear issue ---")
        print(body)
        return
    _linear(COMMENT_CREATE, {"id": issue["id"], "body": body})


def delete_branch(branch: dict, dry: bool) -> None:
    if dry or not branch.get("base") or branch["base"] == "(dry-run)":
        return
    _gh("DELETE", f"/repos/{settings.github_repo}/git/refs/heads/{branch['name']}")


# ----------------------------------------------------------------------- run

def run(dry: bool = True, n: int = 3) -> int:
    """The whole loop. Returns a process exit code."""
    path = RUNS / "latest.json"
    if not path.exists():
        raise SystemExit(f"no run at {path} — `python -m ratchet run --source fixture` first")
    payload = json.loads(path.read_text())
    cases = load_cases()
    if not cases:
        raise SystemExit("no cases on disk — `python -m ratchet run --source fixture` first")
    briefs = target.load_briefs()

    mode = "DRY RUN — no issue, no branch, no PR" if dry else "LIVE — will write to Linear and GitHub"
    print(f"=== ratchet loop ({mode}) ===\n")

    reg = detect(payload, cases)
    if reg is None:
        print("no regression in the current matrix — nothing to fix.")
        return 0

    print(f"1. detected regression")
    print(f"   case      {reg.case_id}")
    print(f"   rule      {reg.rule} — {reg.title}")
    print(f"   broke at  {reg.version} (passed at {reg.prev_version})")
    print(f"   reason    {reg.reason}")
    if reg.quote:
        print(f"   quote     {reg.quote[:100]}")

    issue = create_issue(reg, dry)
    print(f"\n2. linear issue  {issue['identifier']}  {issue['url']}")

    branch = create_branch(reg, dry)
    print(f"3. branch        {branch['name']} (from {branch['base']})")

    cands = propose(reg, n)
    print(f"\n4. proposed {len(cands)} candidate(s)")
    for c in cands:
        print(f"   {c.name}: add={c.add or '—'} remove={c.remove or '—'}")
        print(f"      {c.rationale}")

    print(f"\n5. verifying each against the FULL suite "
          f"({len(cases)} cases) — FAIL_TO_PASS and PASS_TO_PASS")
    verify(cands, reg, cases, briefs, payload)
    baseline = {cid for cid, r in payload["runs"][reg.version]["results"].items()
                if r.get("passed")}
    for c in cands:
        print(f"   {c.name:12} FAIL_TO_PASS={'yes' if c.fail_to_pass else 'no ':3} "
              f"PASS_TO_PASS={'yes' if c.pass_to_pass else 'no ':3}  "
              f"fixed {len(c.fixed)}, broke {len(c.broke)}   {c.verdict_line}")
        if c.broke:
            print(f"        broke: {', '.join(c.broke[:5])}"
                  + (f" (+{len(c.broke) - 5} more)" if len(c.broke) > 5 else ""))

    for c in cands:
        p = commit_candidate(branch["name"], c, reg, dry)
        print(f"   {'would commit' if dry else 'committed'} {p}")

    chosen = next((c for c in cands if c.accepted), None)

    if chosen is None:
        print("\n6. NO CANDIDATE PASSED BOTH CONDITIONS — giving up cleanly.")
        print("   No PR is opened for a fix that does not hold.")
        comment_failure(issue, cands, dry)
        delete_branch(branch, dry)
        print(f"\n   {'would delete' if dry else 'deleted'} branch {branch['name']}")
        _save(reg, issue, branch, cands, None)
        return 1

    after = set(baseline) | set(chosen.fixed)
    body = pr_body(reg, issue, cands, chosen, baseline, after)
    url = open_pr(reg, branch, body, dry)
    print(f"\n6. chose {chosen.name} — {chosen.rationale}")
    print(f"   draft PR: {url}")
    if dry:
        print("\n--- PR body that would be posted ---")
        print(body)
    _save(reg, issue, branch, cands, chosen)
    return 0


def _save(reg: Regression, issue: dict, branch: dict,
          cands: list[Candidate], chosen: Candidate | None) -> None:
    out = RUNS / "loop.json"
    out.write_text(json.dumps({
        "regression": reg.to_dict(),
        "issue": {k: issue[k] for k in ("identifier", "url")},
        "branch": branch,
        "candidates": [c.to_dict() for c in cands],
        "chosen": chosen.name if chosen else None,
    }, indent=2))
    print(f"\nloop state: {out}")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="ratchet loop")
    ap.add_argument("--dry-run", action="store_true",
                    help="print every step and write nothing")
    ap.add_argument("-n", type=int, default=3, help="how many candidates to propose")
    args = ap.parse_args()
    raise SystemExit(run(dry=args.dry_run, n=args.n))


if __name__ == "__main__":
    main()
