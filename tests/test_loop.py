"""The loop's only real job is refusing to open a bad PR.

Everything else it does — filing an issue, cutting a branch, writing a body — is
plumbing. The part that earns trust is the SWE-bench split: a candidate that
fixes the target case and breaks something else must be rejected, not shipped.
That is the test below, and it is hermetic — no network, no model, no suite run.
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ratchet import loop  # noqa: E402
from ratchet.cases import Case  # noqa: E402

REG = loop.Regression(
    case_id="fee_total::meridian", rule="fee_total", brief_id="meridian",
    title="total does not equal the sum of phases", version="v3",
    prev_version="v2", reason="total 92,000 but phases sum to 84,000",
    quote="Total $92,000",
)

# Three cases passed at v3; the regressed one did not.
PAYLOAD = {
    "versions": ["v2", "v3"],
    "runs": {
        "v3": {"results": {
            "fee_total::meridian": {"passed": False, "reason": "total wrong"},
            "headings::meridian":  {"passed": True, "reason": "ok"},
            "excl::meridian":      {"passed": True, "reason": "ok"},
        }},
    },
}
BASELINE = {"headings::meridian", "excl::meridian"}
CASES = [Case(id=cid, rule=cid.split("::")[0], title="t", expectation="e",
              brief_id="meridian", grader="derived", source_app="test",
              source_id="x", source_text="y")
         for cid in PAYLOAD["runs"]["v3"]["results"]]


def run_verify(monkeypatch, passing: set[str], cands: list[loop.Candidate]):
    """Verify `cands` against a suite that returns `passing`, without running one."""
    monkeypatch.setattr(loop.cand_mod, "passing_set", lambda *a, **k: passing)
    return loop.verify(cands, REG, CASES, [{"id": "meridian"}], PAYLOAD)


def candidate(name="candidate-1", add=("totals",), remove=()):
    return loop.Candidate(name=name, add=list(add), remove=list(remove),
                          rationale="r", rules=["totals"])


# ------------------------------------------- the test Phase 2 is judged on

def test_candidate_that_breaks_a_pass_to_pass_case_is_rejected(monkeypatch):
    """Fixes the target, breaks a bystander. This must NOT be accepted.

    An agent that only asks "is the failing test green now?" ships this. The
    whole point of grading per case is that the bystander is visible at all.
    """
    c = candidate()
    # target now passes, but 'excl' — which passed at v3 — has dropped out.
    run_verify(monkeypatch, {"fee_total::meridian", "headings::meridian"}, [c])

    assert c.fail_to_pass is True, "the target case did get fixed"
    assert c.pass_to_pass is False, "but a previously-passing case broke"
    assert c.accepted is False, "a candidate that breaks a bystander must be rejected"
    assert c.broke == ["excl::meridian"], "and the rejection names what it broke"
    assert "broke 1 passing case" in c.verdict_line


def test_candidate_that_fixes_the_target_and_breaks_nothing_is_accepted(monkeypatch):
    c = candidate()
    run_verify(monkeypatch, BASELINE | {"fee_total::meridian"}, [c])
    assert c.fail_to_pass and c.pass_to_pass and c.accepted
    assert c.broke == []
    assert c.verdict_line == "ACCEPTED"


def test_candidate_that_breaks_nothing_but_fixes_nothing_is_rejected(monkeypatch):
    """Green suite, unfixed bug. PASS_TO_PASS alone is not a passing grade."""
    c = candidate()
    run_verify(monkeypatch, BASELINE, [c])
    assert c.fail_to_pass is False
    assert c.pass_to_pass is True
    assert c.accepted is False
    assert "did not fix the target case" in c.verdict_line


def test_no_accepted_candidate_means_no_pr_and_a_non_zero_exit(monkeypatch, capsys, tmp_path):
    """Giving up is a normal path. It must not open a PR and must not exit 0."""
    opened = []
    monkeypatch.setattr(loop, "detect", lambda *a, **k: REG)
    monkeypatch.setattr(loop, "load_cases", lambda: CASES)
    monkeypatch.setattr(loop.target, "load_briefs", lambda: [{"id": "meridian"}])
    monkeypatch.setattr(loop, "propose", lambda reg, n=3: [candidate()])
    # fixes the target, breaks a bystander -> must be rejected
    monkeypatch.setattr(loop.cand_mod, "passing_set",
                        lambda *a, **k: {"fee_total::meridian", "headings::meridian"})
    monkeypatch.setattr(loop, "open_pr", lambda *a, **k: opened.append(1))
    monkeypatch.setattr(loop, "RUNS", tmp_path)
    (tmp_path / "latest.json").write_text(__import__("json").dumps(PAYLOAD))

    code = loop.run(dry=True)

    assert code == 1, "a loop that fixed nothing must exit non-zero"
    assert not opened, "no PR may be opened when no candidate passed"
    out = capsys.readouterr().out
    assert "NO CANDIDATE PASSED BOTH CONDITIONS" in out
    assert "would delete branch" in out


def test_dry_run_writes_nothing(monkeypatch):
    """--dry-run must skip the three write calls, not simulate them badly."""
    def explode(*a, **k):
        raise AssertionError("dry run made a network call")
    monkeypatch.setattr(loop, "_gh", explode)
    monkeypatch.setattr(loop, "_linear", explode)

    issue = loop.create_issue(REG, dry=True)
    branch = loop.create_branch(REG, dry=True)
    path = loop.commit_candidate(branch["name"], candidate(), REG, dry=True)
    url = loop.open_pr(REG, branch, "body", dry=True)

    assert issue["identifier"] == "DRY-000"
    assert branch["name"].startswith("ratchet/fix-")
    assert path.endswith("candidate-1.md")
    assert "dry-run" in url
    loop.delete_branch(branch, dry=True)   # must be a no-op, not a DELETE


def test_branch_name_can_never_be_a_protected_branch():
    """Never write to main. Asserted, not just intended."""
    for bad in ("main", "master", "trunk", "develop"):
        reg = loop.Regression(case_id="x", rule=bad, brief_id="", title="",
                              version="v1", prev_version="v0", reason="")
        try:
            loop.create_branch(reg, dry=True)
        except RuntimeError as e:
            assert "protected" in str(e)
        else:
            # the slug is prefixed, so it is not protected — verify that's why
            assert loop.create_branch(reg, dry=True)["name"].startswith("ratchet/fix-")


def test_detect_finds_the_first_regression_not_a_plain_failure():
    """A case that never passed is a failure, not a regression. Only 'r' counts."""
    cases = [
        Case(id="always_broken::b", rule="always_broken", title="t", expectation="e",
             brief_id="b", grader="derived", source_app="s", source_id="i", source_text="x"),
        Case(id="regressed::b", rule="regressed", title="t", expectation="e",
             brief_id="b", grader="derived", source_app="s", source_id="i", source_text="x"),
    ]
    payload = {
        "versions": ["v1", "v2"],
        "runs": {
            "v1": {"results": {"always_broken::b": {"passed": False, "reason": "no"},
                               "regressed::b": {"passed": True, "reason": "ok"}}},
            "v2": {"results": {"always_broken::b": {"passed": False, "reason": "still no"},
                               "regressed::b": {"passed": False, "reason": "broke"}}},
        },
    }
    reg = loop.detect(payload, cases)
    assert reg is not None
    assert reg.case_id == "regressed::b"
    assert reg.version == "v2" and reg.prev_version == "v1"
    assert reg.reason == "broke"


def test_detect_returns_none_when_nothing_regressed():
    cases = [Case(id="ok::b", rule="ok", title="t", expectation="e", brief_id="b",
                  grader="derived", source_app="s", source_id="i", source_text="x")]
    payload = {"versions": ["v1"], "runs": {"v1": {"results": {"ok::b": {"passed": True}}}}}
    assert loop.detect(payload, cases) is None


def test_pr_body_carries_what_a_reviewer_needs():
    c = candidate()
    c.fail_to_pass, c.pass_to_pass, c.accepted = True, True, True
    c.fixed = ["fee_total::meridian"]
    rejected = candidate(name="candidate-2")
    rejected.fail_to_pass, rejected.pass_to_pass = True, False
    rejected.broke = ["excl::meridian"]

    body = loop.pr_body(REG, {"url": "https://linear.app/x/ISS-1"}, [c, rejected], c,
                        BASELINE, BASELINE | {"fee_total::meridian"})

    assert "https://linear.app/x/ISS-1" in body      # the issue
    assert REG.reason in body                        # the failure that started it
    assert "candidate-1" in body and "candidate-2" in body   # all attempts
    assert "**←chosen**" in body                     # which won
    assert "FAIL_TO_PASS" in body and "PASS_TO_PASS" in body
    assert "`fee_total::meridian`" in body           # the before/after cells
    assert "draft" in body.lower() and "auto-merge" in body.lower()