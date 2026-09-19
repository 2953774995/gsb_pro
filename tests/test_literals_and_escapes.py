"""Literal characters, anchors, dot and escape sequences."""
import pytest

import rex


def test_literal_basic():
    m = rex.compile("abc").search("xxabcxx")
    assert m.group() == "abc"
    assert m.span() == (2, 5)


def test_literal_no_match():
    assert rex.compile("abc").search("abd") is None


def test_match_is_anchored_at_start():
    assert rex.compile("abc").match("xabc") is None
    assert rex.compile("abc").match("abc").group() == "abc"


def test_fullmatch_requires_whole_string():
    assert rex.compile("abc").fullmatch("abc") is not None
    assert rex.compile("abc").fullmatch("abcd") is None
    assert rex.compile("abc").fullmatch("xabc") is None


def test_dot_matches_any_char_but_newline():
    assert rex.compile("a.c").search("axc").group() == "axc"
    assert rex.compile("a.c").search("a\nc") is None
    assert rex.compile("...").search("a\nbc") is None


def test_dot_star_does_not_cross_newline():
    m = rex.compile(".*").search("ab\ncd")
    assert m.group() == "ab"
    assert m.span() == (0, 2)


def test_anchors_without_multiline():
    assert rex.compile("^abc$").fullmatch("abc") is not None
    assert rex.compile("^b").search("a\nb") is None
    assert rex.compile("a$").search("a\nb") is None


def test_escaped_punctuation_is_literal():
    for pat, text in [
        (r"\.", "a.b"),
        (r"\*", "a*b"),
        (r"\+", "a+b"),
        (r"\?", "a?b"),
        (r"\(", "(x)"),
        (r"\)", "(x)"),
        (r"\[", "[x]"),
        (r"\]", "[x]"),
        (r"\|", "a|b"),
        (r"\\", r"a\b"),
        (r"\^", "a^b"),
        (r"\$", "a$b"),
    ]:
        assert rex.compile(pat).search(text) is not None, pat


def test_escaped_specials_do_not_act_special():
    # \. must not match any char
    assert rex.compile(r"a\.c").search("axc") is None
    assert rex.compile(r"a\.c").search("a.c") is not None


def test_control_escapes():
    assert rex.compile(r"a\nb").search("a\nb") is not None
    assert rex.compile(r"a\tb").search("a\tb") is not None
    assert rex.compile(r"a\rb").search("a\rb") is not None
    assert rex.compile(r"a\nb").search("a\tb") is None


def test_shorthand_classes():
    assert rex.compile(r"\d+").search("ab123cd").group() == "123"
    assert rex.compile(r"\D+").search("123abc456").group() == "abc"
    assert rex.compile(r"\w+").search("  foo_1!").group() == "foo_1"
    assert rex.compile(r"\W+").search("abc, def").group() == ", "
    assert rex.compile(r"\s+").search("ab \t\ncd").group() == " \t\n"
    assert rex.compile(r"\S+").search("  abc ").group() == "abc"


def test_hex_escapes():
    assert rex.compile(r"\x41\x42").search("xABy").group() == "AB"
    assert rex.compile(r"A").search("AB") is not None
    assert rex.compile(r"é").search("café") is not None
    assert rex.compile(r"\x4a\x6a").search("Jj").group() == "Jj"


def test_hex_escape_case_insensitive_flag():
    assert rex.compile(r"\x61", rex.IGNORECASE).match("A") is not None


def test_backreference_is_rejected():
    with pytest.raises(rex.RegexError, match="not supported"):
        rex.compile(r"(a)\1")


def test_literal_brace_when_not_a_quantifier():
    # "{,5}" is not a valid quantifier, so "{" is a literal character
    m = rex.compile("a{,5}").search("a{,5}")
    assert m is not None
    assert m.group() == "a{,5}"
