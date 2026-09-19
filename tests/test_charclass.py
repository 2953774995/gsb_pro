"""Character classes: sets, ranges, negation, escapes inside classes."""

import pytest

import regexlab
from regexlab import RegexError


def test_simple_set():
    assert regexlab.fullmatch("[abc]", "b") is not None
    assert regexlab.fullmatch("[abc]", "d") is None


def test_range():
    assert regexlab.fullmatch("[a-z]", "m") is not None
    assert regexlab.fullmatch("[a-z]", "M") is None
    assert regexlab.fullmatch("[a-zA-Z0-9]", "Q") is not None


def test_negated_class():
    assert regexlab.fullmatch("[^a-z]", "A") is not None
    assert regexlab.fullmatch("[^a-z]", "a") is None


def test_negated_class_still_needs_a_char():
    assert regexlab.fullmatch("[^a]", "") is None


def test_class_with_quantifier():
    m = regexlab.match("[0-9]+", "12345abc")
    assert m.group(0) == "12345"


def test_predefined_class_inside_brackets():
    assert regexlab.fullmatch(r"[\d]", "5") is not None
    assert regexlab.fullmatch(r"[\d]", "a") is None
    assert regexlab.fullmatch(r"[\D]", "a") is not None
    assert regexlab.fullmatch(r"[\w-]+", "ab-c_9") is not None


def test_dash_at_edges_is_literal():
    assert regexlab.fullmatch("[a-]", "-") is not None
    assert regexlab.fullmatch("[-a]", "-") is not None
    assert regexlab.fullmatch("[a-]", "b") is None


def test_closing_bracket_first_is_literal():
    assert regexlab.fullmatch("[]a]", "]") is not None
    assert regexlab.fullmatch("[^]a]", "]") is None
    assert regexlab.fullmatch("[^]a]", "b") is not None


def test_caret_not_first_is_literal():
    assert regexlab.fullmatch("[a^]", "^") is not None


def test_escaped_chars_inside_class():
    assert regexlab.fullmatch(r"[\]]", "]") is not None
    assert regexlab.fullmatch(r"[\\]", "\\") is not None
    assert regexlab.fullmatch(r"[\n]", "\n") is not None


def test_out_of_order_range_is_error():
    with pytest.raises(RegexError) as exc:
        regexlab.compile("[z-a]")
    assert "range" in str(exc.value).lower()


def test_unterminated_class_is_error():
    with pytest.raises(RegexError):
        regexlab.compile("[abc")


def test_predefined_class_as_range_endpoint_is_error():
    with pytest.raises(RegexError):
        regexlab.compile(r"[a-\d]")
