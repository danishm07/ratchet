import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ratchet.cases import Case  # noqa: E402
from ratchet import matrix  # noqa: E402


def _case(cid):
    return Case(id=cid, rule="date", title="t", expectation="e", brief_id="b",
                grader="deterministic", source_app="slack", source_id="1",
                source_text="x")


def _payload(states):
    versions = ["v1", "v2", "v3"]
    runs = {v: {"results": {}} for v in versions}
    for cid, seq in states.items():
        for v, ok in zip(versions, seq):
            runs[v]["results"][cid] = {"passed": ok, "reason": "", "quote": ""}
    return {"versions": versions, "runs": runs}


def test_regression_is_distinguished_from_a_persistent_failure():
    cases = [_case("a"), _case("b")]
    m = matrix.build(_payload({"a": [True, False, True], "b": [False, False, False]}), cases)
    a, b = m["rows"]
    assert a["states"] == ["p", "r", "p"], "pass then fail is a regression"
    assert b["states"] == ["f", "f", "f"], "never passing is not a regression"


def test_per_version_counts_regressions():
    cases = [_case("a"), _case("b")]
    m = matrix.build(_payload({"a": [True, False, False], "b": [True, True, False]}), cases)
    assert m["per_version"][1]["regressions"] == ["a"]
    assert m["per_version"][2]["regressions"] == ["b"]


def test_aggregate_can_hide_a_regression():
    """The reason the product exists: one number stays flat while a case breaks."""
    cases = [_case("a"), _case("b")]
    m = matrix.build(_payload({"a": [True, False, False], "b": [False, True, True]}), cases)
    scores = [pv["score"] for pv in m["per_version"]]
    assert scores[0] == scores[1] == 0.5, "score is unchanged"
    assert m["per_version"][1]["regressions"] == ["a"], "but a case regressed"
