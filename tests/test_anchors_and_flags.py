"""Anchors ^ $ and the IGNORECASE / MULTILINE compile flags."""
import rex
from rex import IGNORECASE as I, MULTILINE as M


def test_caret_matches_only_at_start_by_default():
    assert rex.compile("^b").search("ab") is None
    assert rex.compile("^a").search("ab").span() == (0, 1)


def test_dollar_matches_only_at_end_by_default():
    assert rex.compile("a$").search("ab") is None
    assert rex.compile("b$").search("ab").span() == (1, 2)
    # no implicit "before trailing newline" behaviour
    assert rex.compile("b$").search("ab\n") is None


def test_multiline_caret_matches_after_newline():
    p = rex.compile("^b", M)
    assert p.search("a\nb").span() == (2, 3)
    assert rex.compile("^b").search("a\nb") is None


def test_multiline_dollar_matches_before_newline():
    p = rex.compile("a$", M)
    assert p.search("a\nb").span() == (0, 1)
    assert rex.compile("a$").search("a\nb") is None


def test_multiline_findall_line_starts():
    p = rex.compile(r"^\w+", M)
    assert p.findall("ab\ncd\nef") == ["ab", "cd", "ef"]


def test_multiline_findall_line_ends():
    p = rex.compile(r"\w+$", M)
    assert p.findall("ab\ncd") == ["ab", "cd"]


def test_multiline_anchors_still_match_string_edges():
    p = rex.compile("^a", M)
    assert p.search("a\nb").span() == (0, 1)
    p = rex.compile("b$", M)
    assert p.search("a\nb").span() == (2, 3)


def test_empty_pattern_with_anchors():
    assert rex.compile("^$").fullmatch("") is not None
    assert rex.compile("^$").search("x") is None
    assert rex.compile("^$", M).search("a\n\nb").span() == (2, 2)


def test_ignorecase_literals():
    p = rex.compile("hello", I)
    assert p.match("HELLO") is not None
    assert p.match("HeLLo") is not None
    assert p.match("hello") is not None
    assert rex.compile("hello").match("HELLO") is None


def test_ignorecase_char_class():
    assert rex.compile("[a-z]+", I).fullmatch("AbC") is not None
    assert rex.compile("[A-Z]+", I).fullmatch("abc") is not None
    assert rex.compile("[^a-z]", I).search("B") is None


def test_ignorecase_escapes():
    assert rex.compile(r"\x41", I).match("a") is not None
    assert rex.compile(r"A", I).match("a") is not None


def test_flags_combine():
    p = rex.compile("^abc$", I | M)
    assert p.search("xx\nABC\nyy").span() == (3, 6)


def test_unknown_flag_rejected():
    import pytest
    with pytest.raises(rex.RegexError, match="unknown flag"):
        rex.compile("a", flags=0x100)


def test_flag_aliases():
    assert rex.I is rex.IGNORECASE
    assert rex.M is rex.MULTILINE
