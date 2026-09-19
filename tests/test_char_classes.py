"""Character classes: ranges, negation, escapes and empty classes."""

import pytest

import rex


def test_simple_class():
    p = rex.compile("[abc]")
    assert p.match("a") is not None
    assert p.match("b") is not None
    assert p.match("c") is not None
    assert p.match("d") is None


def test_negated_class():
    p = rex.compile("[^abc]")
    assert p.match("d") is not None
    assert p.match("a") is None
    assert rex.compile("[^abc]+").match("xyzabc").group() == "xyz"


def test_ranges():
    p = rex.compile("[a-z0-9]+")
    assert p.match("hello123").group() == "hello123"
    assert p.match("ABC") is None
    assert rex.compile("[A-Z]+").match("ABCdef").group() == "ABC"
    assert rex.compile("[a-c-e]+").match("abcde") is not None


def test_range_out_of_order_raises():
    with pytest.raises(rex.RegexError):
        rex.compile("[z-a]")


def test_dash_as_literal():
    assert rex.compile("[a-]").match("-") is not None
    assert rex.compile("[-a]").match("-") is not None
    assert rex.compile("[a-]").match("b") is None
    assert rex.compile(r"[a\-z]").match("-") is not None


def test_caret_as_literal_when_not_first():
    assert rex.compile("[a^]").match("^") is not None
    assert rex.compile("[a^]").match("b") is None


def test_escapes_inside_class():
    assert rex.compile(r"[\d]+").match("42") is not None
    assert rex.compile(r"[\d.]+").match("3.14").group() == "3.14"
    assert rex.compile(r"[^\d]+").match("ab1").group() == "ab"
    assert rex.compile(r"[\]]").match("]") is not None
    assert rex.compile(r"[\-]").match("-") is not None
    assert rex.compile(r"[\x41-\x43]+").match("ABC") is not None
    assert rex.compile(r"[\n]").match("\n") is not None


def test_closing_bracket_as_first_literal():
    assert rex.compile("[]a]").match("]") is not None
    assert rex.compile("[]a]").match("a") is not None
    assert rex.compile("[^]a]").match("b") is not None
    assert rex.compile("[^]a]").match("]") is None


def test_unterminated_class_raises():
    with pytest.raises(rex.RegexError):
        rex.compile("[abc")


def test_empty_class_raises():
    # "[]" starts a class whose first char is a literal "]", so the
    # class itself is never closed -> RegexError.
    with pytest.raises(rex.RegexError):
        rex.compile("[]")


def test_class_case_insensitive():
    p = rex.compile("[a-z]+", rex.IGNORECASE)
    assert p.match("ABC").group() == "ABC"
