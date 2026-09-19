"""Literal characters, anchors, dot and escape sequences."""

import pytest

import rex


def test_plain_literal_search():
    m = rex.compile("abc").search("xxabcxx")
    assert m is not None
    assert m.span() == (2, 5)
    assert m.group(0) == "abc"


def test_literal_match_and_fullmatch():
    p = rex.compile("abc")
    assert p.match("abcdef").group() == "abc"
    assert p.match("xabc") is None
    assert p.fullmatch("abc") is not None
    assert p.fullmatch("abcd") is None


def test_no_match_returns_none():
    assert rex.compile("zzz").search("hello") is None


def test_anchors():
    assert rex.compile("^abc").search("abc") is not None
    assert rex.compile("^abc").search("xabc") is None
    assert rex.compile("abc$").search("abc") is not None
    assert rex.compile("abc$").search("abcx") is None
    assert rex.compile("^abc$").fullmatch("abc") is not None


def test_dot_matches_anything_but_newline():
    p = rex.compile(".")
    assert p.match("a").group() == "a"
    assert p.match("\n") is None
    assert rex.compile("a.c").match("abc") is not None
    assert rex.compile("a.c").match("a\nc") is None
    assert rex.compile(".*").fullmatch("a\nb") is None
    assert rex.compile(".*").findall("a\nb") == ["a", "", "b", ""]


def test_control_escapes():
    assert rex.compile(r"\n").match("\n") is not None
    assert rex.compile(r"\t").match("\t") is not None
    assert rex.compile(r"\r").match("\r") is not None
    assert rex.compile(r"a\nb").match("a\nb") is not None


def test_punctuation_escapes():
    for escaped, char in [
        (r"\\", "\\"), (r"\.", "."), (r"\*", "*"), (r"\+", "+"),
        (r"\?", "?"), (r"\(", "("), (r"\)", ")"), (r"\[", "["),
        (r"\]", "]"), (r"\|", "|"),
    ]:
        assert rex.compile(escaped).match(char) is not None, escaped
    assert rex.compile(r"a\.b").match("a.b") is not None
    assert rex.compile(r"a\.b").match("axb") is None
    assert rex.compile(r"a\*b").match("a*b") is not None
    assert rex.compile(r"a\|b").match("a|b") is not None


def test_hex_escapes():
    assert rex.compile(r"\x41").match("A") is not None
    assert rex.compile(r"\x41\x42\x43").match("ABC") is not None
    assert rex.compile(r"A").match("A") is not None
    assert rex.compile(r"€").match("€") is not None


def test_class_escapes_outside_brackets():
    assert rex.compile(r"\d+").match("123abc").group() == "123"
    assert rex.compile(r"\D+").match("abc123").group() == "abc"
    assert rex.compile(r"\w+").match("hi_5!").group() == "hi_5"
    assert rex.compile(r"\W+").match("!?ab").group() == "!?"
    assert rex.compile(r"\s+").match(" \t\nx").group() == " \t\n"
    assert rex.compile(r"\S+").search("  hello  ").group() == "hello"


def test_unknown_escape_raises():
    with pytest.raises(rex.RegexError):
        rex.compile(r"\q")


def test_trailing_backslash_raises():
    with pytest.raises(rex.RegexError):
        rex.compile("abc\\")


def test_backreference_not_supported():
    with pytest.raises(rex.RegexError) as excinfo:
        rex.compile(r"(a)\1")
    assert "not supported" in str(excinfo.value)
