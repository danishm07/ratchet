"""Graders are the measuring instrument. If they are wrong, every number is.

These are regression tests in the literal sense: the markdown-blindness bug that
scored section presence at random is pinned here so it cannot come back.
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ratchet import judge  # noqa: E402

BRIEF = {
    "id": "t", "client": "Testco", "client_legal_name": "Testco Ltd",
    "currency": "USD", "engagement_length_months": 12,
    "phases": [{"name": "A", "fee": 48000}, {"name": "B", "fee": 36000}],
}


def test_totals_catches_bad_arithmetic():
    assert not judge.g_totals("Phase A $48,000\nPhase B $36,000\nTotal $92,000", BRIEF).passed
    assert judge.g_totals("Phase A $48,000\nPhase B $36,000\nTotal $84,000", BRIEF).passed


def test_percent_words_must_match_numeral():
    """The captured run of words is longer than the number word itself; resolving
    only the trailing token is what makes the mismatch visible."""
    assert not judge.g_percent("a deposit of fifty percent (20%) is due", BRIEF).passed
    assert judge.g_percent("a deposit of fifty percent (50%) is due", BRIEF).passed
    assert not judge.g_percent("payable at one hundred percent (50%)", BRIEF).passed
    assert judge.g_percent("payable at one hundred percent (100%)", BRIEF).passed
    assert not judge.g_percent("a deposit of twenty-five percent (30%)", BRIEF).passed


def test_date_rejects_misspelled_month_and_wrong_format():
    assert not judge.g_date("Term commences Jume 14, 2026.", BRIEF).passed
    assert not judge.g_date("Term commences June 14, 2026.", BRIEF).passed
    assert judge.g_date("Term commences 14 June 2026.", BRIEF).passed


def test_currency_rejects_mixed_symbols():
    assert not judge.g_currency("Phase A $48,000\nPhase B £36,000", BRIEF).passed
    assert judge.g_currency("Phase A $48,000\nPhase B $36,000", BRIEF).passed


def test_daterange_rejects_inverted_dates():
    assert not judge.g_daterange("Start: 1 September 2026\nEnd: 14 August 2026", BRIEF).passed
    assert judge.g_daterange("Start: 1 September 2026\nEnd: 14 October 2026", BRIEF).passed


def test_termmatch_compares_against_the_brief():
    assert not judge.g_termmatch("The term is six (6) months.", BRIEF).passed
    assert judge.g_termmatch("The term is twelve (12) months.", BRIEF).passed


def test_headings_tolerate_markdown_emphasis():
    """The bug that made the first run's seesaw a measurement artefact."""
    md = "**1. Scope of Services**\n**2. Our Approach**\n**3. Fees**\n**4. Timeline**"
    plain = "1. Scope of Services\n2. Our Approach\n3. Fees\n4. Timeline"
    atx = "## 1. Scope of Services\n## 2. Our Approach\n## 3. Fees\n## 4. Timeline"
    for doc in (md, plain, atx):
        assert judge.g_headings(doc, BRIEF).passed, doc[:20]
    assert not judge.g_headings("Scope of Services\nOur Approach", BRIEF).passed


def test_sections_tolerate_markdown_emphasis():
    g = judge.GRADERS["assume"]
    for doc in ("**5. Assumptions**\n- a\n- b", "5. Assumptions\n- a", "## Assumptions\n- a"):
        assert g(doc, BRIEF).passed, doc[:20]
    assert not g("Scope of Services only", BRIEF).passed


def test_legalname_short_circuits_when_brief_supplies_one():
    """No LLM call should be needed when the brief already has a legal name."""
    v = judge.g_legalname("Between Testco Ltd and Northwind.", BRIEF)
    assert v.passed and v.grader == "deterministic"


def test_generated_graders_never_score_a_suite():
    """Only measured graders score. An unknown rule raises rather than guessing.

    This is the regression that mattered: when judge.grade() fell back to a
    generated grader, every version scored 60/60 and the suite stopped finding
    anything. Missing data is a distinct state from a passing case.
    """
    import pytest
    from ratchet.cases import Case

    c = Case(id="invented::t", rule="invented_rule", title="t",
             expectation="something a model made up", brief_id="t",
             grader="derived", source_app="s", source_id="i", source_text="x")
    with pytest.raises(RuntimeError) as e:
        judge.grade(c, "any document at all", BRIEF)
    assert "no grader registered" in str(e.value)
    assert "compare-graders" in str(e.value), "the error should say where generation lives"


def test_reference_cases_cover_every_rule_and_brief():
    briefs = [{"id": "a"}, {"id": "b"}]
    cases = judge.reference_cases(briefs)
    assert len(cases) == len(judge.REFERENCE_RULES) * 2
    assert {c.rule for c in cases} == set(judge.GRADERS)
    # every one of them must be gradeable by a hand-written grader
    assert all(c.rule in judge.GRADERS for c in cases)
    assert {c.grader for c in cases} == {"deterministic", "llm"}


def test_every_reference_rule_has_a_grader():
    """The reference set and the hand-written graders must stay in lockstep —
    `compare-graders` generates one grader per REFERENCE_RULES entry and measures
    it against GRADERS[rule], so a rule in one and not the other is a silent hole."""
    assert set(judge.REFERENCE_RULES) == set(judge.GRADERS)
    assert all(judge.REFERENCE_RULES[r].strip() for r in judge.REFERENCE_RULES)
