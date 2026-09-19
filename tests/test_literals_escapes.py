"""Literals, wildcards, anchors and escape-sequence boundary tests."""

import pytest

import rex
from rex.errors import RegexError


def test_plain_literal_search_match_fullmatch():
    p = rex.compile("abc")
    m = p.search("xxabcyy")
    assert m is not None
    assert m.group() == "abc"
    assert m.span() == (2, 5)
    assert m.start() == 2 and m.end() == 5
    assert p.match("xxabc") is None
    assert p.match("abcxx").group() == "abc"
    assert p.fullmatch("abc") is not None
    assert p.fullmatch("abcd") is None


def test_literal_special_punctuation():
    for ch in ".+*?()[]{}|^$\\":
        pat = "\\" + ch
        assert rex.compile(pat).search("a" + ch + "b").group() == ch


def test_dot_does_not_match_newline():
    p = rex.compile("a.b")
    assert p.fullmatch("axb") is not None
    assert p.search("a\nb") is None
    assert rex.compile(".").findall("a\nb") == ["a", "b"]


def test_anchors_start_end():
    assert rex.compile("^abc").search("xxabc") is None
    assert rex.compile("abc$").search("abcxx") is None
    m = rex.compile("^abc$").fullmatch("abc")
    assert m is not None
    assert rex.compile("^$").search("") is not None
    assert rex.compile("^$").search("x") is None


def test_end_anchor_before_trailing_newline_default_mode():
    assert rex.compile("abc$").search("abc\n") is not None
    assert rex.compile("abc$").search("abc\n\n") is None
    assert rex.compile("abc$").search("abc\ndef") is None


def test_simple_escapes():
    assert rex.compile(r"\n").search("a\nb").group() == "\n"
    assert rex.compile(r"\t").search("x\ty").group() == "\t"
    assert rex.compile(r"\r").search("x\ry").group() == "\r"
    assert rex.compile(r"\\").search(r"a\b").group() == "\\"
    assert rex.compile(r"\.").search("a.b").group() == "."


def test_hex_escapes():
    assert rex.compile(r"\x41").search("A").group() == "A"
    assert rex.compile(r"\x4a").fullmatch("J") is not None
    assert rex.compile(r"\u0041").search("A").group() == "A"
    assert rex.compile(r"\u00e9").search("caf\u00e9").group() == "\u00e9"


def test_hex_escape_boundary_errors():
    with pytest.raises(RegexError) as exc:
        rex.compile(r"\x4")
    assert exc.value.pos == 0
    with pytest.raises(RegexError):
        rex.compile(r"\u004")
    with pytest.raises(RegexError):
        rex.compile(r"\xZZ")


def test_unknown_escape_reports_column():
    with pytest.raises(RegexError) as exc:
        rex.compile(r"ab\q")
    assert exc.value.pos == 2
    assert "column 3" in str(exc.value)


def test_dangling_backslash():
    with pytest.raises(RegexError) as exc:
        rex.compile("abc\\")
    assert exc.value.pos == 3


def test_builtin_shorthands():
    assert rex.compile(r"\d+").findall("a12 b34") == ["12", "34"]
    assert rex.compile(r"\D+").findall("1ab2") == ["ab"]
    assert rex.compile(r"\w+").findall("a_b c9!") == ["a_b", "c9"]
    assert rex.compile(r"\W+").findall("ab!@#cd") == ["!@#"]
    assert rex.compile(r"\s+").findall("a b\tc\nd") == [" ", "\t", "\n"]
    assert rex.compile(r"\S+").findall("a b\nc") == ["a", "b", "c"]


def test_unicode_shorthands():
    assert rex.compile(r"\w").search("\u00e9").group() == "\u00e9"
    assert rex.compile(r"\d").search("\u0661") is not None  # Arabic-Indic digit
