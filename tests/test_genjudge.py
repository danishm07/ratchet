"""Generated graders are a measuring instrument too, so they get pinned like one.

Every test here is hermetic: the model call is replaced with a canned response,
so what is under test is *our* handling of what a model returns — the parsing,
the safety refusals, and whether the resulting spec actually catches the failure
it was derived from. Testing the model's taste is what `compare-graders` is for,
and that needs the real corpus, not a unit test.
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import json  # noqa: E402

from ratchet import genjudge  # noqa: E402

BRIEF = {
    "id": "t", "client": "Testco", "client_legal_name": None,
    "currency": "USD", "engagement_length_months": 12,
    "phases": [{"name": "A", "fee": 48000}, {"name": "B", "fee": 36000}],
}

GOOD_DOC = """## 1. Scope of Services
Work as described.

## 5. Assumptions
- a
- b

## 6. Exclusions
- Travel is not included.

Total $84,000. The term is twelve (12) months.
"""

BAD_DOC = """## 1. Scope of Services
Work as described.

## 5. Assumptions
- a

Total $92,000. The term is six (6) months.
"""


def canned(monkeypatch, payload: dict) -> None:
    """Make the next derive_spec call return `payload` without touching a model."""
    monkeypatch.setattr(genjudge, "complete_json", lambda *a, **k: payload)


# ------------------------------------------------- the test Phase 1 is judged on

def test_generated_regex_present_catches_the_failure_it_was_derived_from(monkeypatch):
    """The point of the whole phase: describe a failure, get a grader that finds it.

    The expectation is the one a human wrote. The spec comes back through the
    real parsing path. The resulting grader must fail the document that has no
    Exclusions section and pass the one that does — otherwise generation has
    produced something that looks like a grader and measures nothing.
    """
    canned(monkeypatch, {
        "kind": "regex_present",
        "pattern": r"^\s*(?:#{1,4}\s*)?(?:\*\*)?\s*(?:\d\.\s*)?Exclusions\b",
        "field": None,
        "steps": [],
        "rationale": "section presence is a pattern match, no model needed",
    })
    spec = genjudge.derive_spec("an Exclusions section listing what is out of scope must be present")

    assert spec.kind == "regex_present"

    missing = genjudge.grade_generated(spec, BAD_DOC, BRIEF)
    present = genjudge.grade_generated(spec, GOOD_DOC, BRIEF)

    assert not missing.passed, "generated grader missed the failure it was derived from"
    assert present.passed
    assert present.quote, "a passing verdict must point at the text that decided it"


def test_generated_grader_agrees_with_the_hand_written_one_it_replaces(monkeypatch):
    """Same documents, same answers as judge.g_section('Exclusions')."""
    from ratchet import judge

    canned(monkeypatch, {
        "kind": "regex_present",
        "pattern": r"^\s*(?:#{1,4}\s*)?(?:\*\*)?\s*(?:\d\.\s*)?Exclusions\b",
        "field": None, "steps": [], "rationale": "",
    })
    spec = genjudge.derive_spec("an Exclusions section must be present")
    hand = judge.GRADERS["excl"]
    for doc in (GOOD_DOC, BAD_DOC):
        assert genjudge.grade_generated(spec, doc, BRIEF).passed == hand(doc, BRIEF).passed


# ------------------------------------------------------------- the other kinds

def test_regex_absent_fails_when_the_forbidden_thing_is_present(monkeypatch):
    canned(monkeypatch, {
        "kind": "regex_absent", "pattern": r"\b(?:Ltd|LLC|Inc\.|GmbH)\b",
        "field": None, "steps": [], "rationale": "",
    })
    spec = genjudge.derive_spec("never invent a legal suffix the brief did not supply")
    bad = genjudge.grade_generated(spec, "Between Testco Ltd and Northwind.", BRIEF)
    assert not bad.passed
    assert bad.quote == "Ltd", "a failing verdict must quote what decided it"
    assert genjudge.grade_generated(spec, "Between [CLIENT LEGAL NAME] and Northwind.", BRIEF).passed


def test_numeric_match_compares_against_a_derived_brief_field(monkeypatch):
    canned(monkeypatch, {
        "kind": "numeric_match", "pattern": r"total[^\n\d]{0,40}\$?\s?([\d,]{4,})",
        "field": "phases_fee_sum", "steps": [], "rationale": "",
    })
    spec = genjudge.derive_spec(
        "the stated total must equal the sum of the phase fees",
        fields=sorted(genjudge.brief_fields(BRIEF)))
    assert spec.kind == "numeric_match"
    assert not genjudge.grade_generated(spec, BAD_DOC, BRIEF).passed   # 92,000 vs 84,000
    assert genjudge.grade_generated(spec, GOOD_DOC, BRIEF).passed      # 84,000


def test_numeric_match_resolves_a_spelled_number(monkeypatch):
    canned(monkeypatch, {
        "kind": "numeric_match", "pattern": r"term is (\w+)\s*\(\d{1,2}\)\s*months?",
        "field": "engagement_length_months", "steps": [], "rationale": "",
    })
    spec = genjudge.derive_spec("the stated term must match the brief",
                                fields=sorted(genjudge.brief_fields(BRIEF)))
    assert genjudge.grade_generated(spec, GOOD_DOC, BRIEF).passed      # twelve
    assert not genjudge.grade_generated(spec, BAD_DOC, BRIEF).passed   # six


def test_brief_fields_are_introspected_not_hardcoded():
    """A different brief schema must expose a different menu with no code change."""
    f = genjudge.brief_fields(BRIEF)
    assert f["phases_fee_sum"] == 84000
    assert f["phases_count"] == 2
    assert f["engagement_length_months"] == 12
    assert "client" not in f, "non-numeric keys are not comparable"

    other = genjudge.brief_fields({"retainer": 5000, "milestones": [{"cost": 10}, {"cost": 20}]})
    assert other == {"retainer": 5000.0, "milestones_count": 2.0, "milestones_cost_sum": 30.0}


# ------------------------------------------------------ refusing unusable specs

def test_uncompilable_pattern_degrades_to_a_rubric_and_says_so(monkeypatch):
    canned(monkeypatch, {"kind": "regex_present", "pattern": "([unclosed",
                         "field": None, "steps": [], "rationale": ""})
    spec = genjudge.derive_spec("something must be present")
    assert spec.kind == "llm_rubric"
    assert "does not compile" in spec.rationale


def test_nested_quantifier_is_refused(monkeypatch):
    """Python's re has no timeout, so (x+)+ is never run."""
    canned(monkeypatch, {"kind": "regex_present", "pattern": r"(\d+)+ dollars",
                         "field": None, "steps": [], "rationale": ""})
    spec = genjudge.derive_spec("a fee must be present")
    assert spec.kind == "llm_rubric"
    assert "backtracking" in spec.rationale


def test_numeric_match_needs_exactly_one_capture_group(monkeypatch):
    canned(monkeypatch, {"kind": "numeric_match", "pattern": r"(total)\D*([\d,]+)",
                         "field": "phases_fee_sum", "steps": [], "rationale": ""})
    spec = genjudge.derive_spec("the total must match", fields=["phases_fee_sum"])
    assert spec.kind == "llm_rubric"
    assert "capture group" in spec.rationale


def test_numeric_match_rejects_a_field_the_brief_does_not_have(monkeypatch):
    canned(monkeypatch, {"kind": "numeric_match", "pattern": r"([\d,]+)",
                         "field": "invented_field", "steps": [], "rationale": ""})
    spec = genjudge.derive_spec("some number must match", fields=["phases_fee_sum"])
    assert spec.kind == "llm_rubric"
    assert "unknown brief field" in spec.rationale


def test_unparseable_model_response_degrades_to_a_rubric(monkeypatch):
    monkeypatch.setattr(genjudge, "complete_json", lambda *a, **k: None)
    spec = genjudge.derive_spec("the letter states a 30-day return window")
    assert spec.kind == "llm_rubric"
    assert "no usable spec" in spec.rationale
    assert spec.steps, "a fallback rubric still has to have something to grade against"


def test_no_generated_code_is_ever_executed():
    """The safety property, asserted against the AST rather than the text.

    A grep would trip over `re.compile` and over this very docstring, so parse
    instead: no bare call to exec/eval/compile/__import__, and no import of a
    module that could run something.
    """
    import ast

    tree = ast.parse(pathlib.Path(genjudge.__file__).read_text())
    banned_calls = {"exec", "eval", "compile", "__import__"}
    banned_imports = {"subprocess", "os", "importlib", "ctypes"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in banned_calls, \
                f"genjudge.py calls {node.func.id}() at line {node.lineno}"
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] not in banned_imports, f"imports {a.name}"
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in banned_imports, f"imports {node.module}"


def test_spec_round_trips_through_json():
    """Specs get cached and shown in reports, so they must serialise."""
    spec = genjudge.GraderSpec(kind="regex_present", pattern=r"\bExclusions\b",
                               rationale="x")
    assert json.loads(json.dumps(spec.to_dict()))["pattern"] == r"\bExclusions\b"
