"""Character classes: ranges, negation, escapes, empty classes."""
import pytest

import rex


def test_simple_set():
    p = rex.compile("[abc]")
    assert p.search("zb").group() == "b"
    assert p.search("zd") is None


def test_ranges():
    p = rex.compile("[a-z0-9]+")
    assert p.search("!!abz019!!").group() == "abz019"
    assert p.search("ABC") is None


def test_multiple_ranges():
    assert rex.compile("[a-zA-Z]+").match("Hello123").group() == "Hello"


def test_negated_class():
    p = rex.compile("[^abc]+")
    assert p.search("abxyzab").group() == "xyz"
    assert p.search("abc") is None


def test_negated_class_matches_newline():
    # negated classes DO match \n (unlike ".")
    assert rex.compile("[^a]").search("\n") is not None


def test_dash_at_edges_is_literal():
    assert rex.compile("[-a]").search("-") is not None
    assert rex.compile("[a-]").search("-") is not None
    assert rex.compile("[a-]").search("b") is None


def test_caret_is_literal_when_not_first():
    assert rex.compile("[a^]").search("^") is not None


def test_closing_bracket_first_is_literal():
    assert rex.compile("[]]").search("]") is not None
    assert rex.compile("[^]]+").search("]ab").group() == "ab"


def test_escapes_inside_class():
    assert rex.compile(r"[\d]+").search("ab12").group() == "12"
    assert rex.compile(r"[\]]").search("]") is not None
    assert rex.compile(r"[\-]").search("-") is not None
    assert rex.compile(r"[\\]").search("\\") is not None
    assert rex.compile(r"[\x41-\x5a]+").match("ABC").group() == "ABC"
    assert rex.compile(r"[\n]").search("\n") is not None
    assert rex.compile(r"[\w.]+").match("a.b_1!").group() == "a.b_1"


def test_negated_shorthand_inside_class():
    assert rex.compile(r"[\D]+").search("12ab34").group() == "ab"
    assert rex.compile(r"[\S]+").search("  abc ").group() == "abc"


def test_class_case_insensitive_flag():
    assert rex.compile("[a-z]+", rex.IGNORECASE).match("ABC") is not None
    assert rex.compile("[^a-z]", rex.IGNORECASE).search("B") is None


def test_empty_class_is_an_error():
    # "[]" can never be a valid (terminated) class
    with pytest.raises(rex.RegexError):
        rex.compile("[]")
    with pytest.raises(rex.RegexError):
        rex.compile("[^]")


def test_unterminated_class():
    with pytest.raises(rex.RegexError) as exc:
        rex.compile("[abc")
    assert "unterminated character class" in str(exc.value)
    assert "column 1" in str(exc.value)


def test_bad_range_reversed():
    with pytest.raises(rex.RegexError, match="bad character range"):
        rex.compile("[z-a]")


def test_class_repeat():
    assert rex.compile("[0-9]{3}").search("ab1234").group() == "123"
