"""complete_json is load-bearing for every module, so its parse is pinned here.

The bug these pin cost five of ten generated graders and was invisible from the
outside: the parse *succeeded*, it just returned the wrong value. A nested array
was mistaken for the whole response, four fields were silently dropped, and the
caller fell back to a lenient default that passed everything.
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ratchet import llm  # noqa: E402


def parse(raw: str):
    """complete_json's parsing, without the model call."""
    import json, re
    raw = llm._FENCE.sub("", raw.strip()).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    span = llm._first_json_value(raw)
    return json.loads(span) if span else None


def test_object_containing_an_array_parses_as_the_object():
    """The exact shape every GraderSpec comes back as."""
    raw = '{"kind": "llm_rubric", "pattern": null, "steps": ["a", "b"], "rationale": "why"}'
    got = parse(raw)
    assert isinstance(got, dict), "an object with a nested array must parse as the object"
    assert got["kind"] == "llm_rubric"
    assert got["steps"] == ["a", "b"]
    assert got["rationale"] == "why"


def test_a_bare_array_still_parses_as_an_array():
    """loop.propose asks for one of these; it must not regress."""
    got = parse('[{"add": ["date"], "remove": []}, {"add": [], "remove": ["x"]}]')
    assert isinstance(got, list) and len(got) == 2
    assert got[0]["add"] == ["date"]


def test_braces_inside_a_regex_string_do_not_end_the_object():
    """Generated patterns are full of {1,4} and [^\\]]; the scanner tracks strings."""
    raw = r'{"kind": "regex_present", "pattern": "^\\s*(?:#{1,4}\\s*)?\\[CLIENT\\]", "steps": []}'
    got = parse(raw)
    assert isinstance(got, dict)
    assert got["pattern"] == r"^\s*(?:#{1,4}\s*)?\[CLIENT\]"


def test_escaped_quote_inside_a_string_does_not_end_it():
    raw = r'{"kind": "regex_absent", "pattern": "say \"hi\" now", "steps": []}'
    got = parse(raw)
    assert isinstance(got, dict)
    assert got["pattern"] == 'say "hi" now'


def test_prose_around_the_json_is_ignored():
    raw = 'Here is the spec you asked for:\n{"kind": "regex_present", "steps": ["x"]}\nHope that helps.'
    got = parse(raw)
    assert isinstance(got, dict) and got["kind"] == "regex_present"


def test_fenced_json_parses():
    raw = '```json\n{"kind": "numeric_match", "field": "phases_fee_sum", "steps": []}\n```'
    got = parse(raw)
    assert isinstance(got, dict) and got["field"] == "phases_fee_sum"


def test_no_json_at_all_returns_none():
    assert parse("I could not do that.") is None
    assert llm._first_json_value("nothing here") is None


def test_unterminated_object_returns_none():
    assert parse('{"kind": "regex_present", "pattern": "abc"') is None
