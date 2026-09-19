"""Empty pattern / empty input / empty-string edge cases."""
import rex


def test_empty_pattern_matches_empty_at_start():
    m = rex.compile("").search("abc")
    assert m.group() == ""
    assert m.span() == (0, 0)


def test_empty_pattern_fullmatch():
    assert rex.compile("").fullmatch("") is not None
    assert rex.compile("").fullmatch("a") is None


def test_empty_input():
    assert rex.compile("a").search("") is None
    assert rex.compile("a*").fullmatch("") is not None
    assert rex.compile("a+").fullmatch("") is None
    assert rex.compile("^$").match("") is not None
    assert rex.compile(".").search("") is None


def test_pattern_matching_empty_string():
    m = rex.compile("a*").search("bbb")
    assert m.group() == ""
    assert m.span() == (0, 0)


def test_optional_everything():
    p = rex.compile("(?:a?)*")
    assert p.fullmatch("") is not None
    assert p.fullmatch("aaa") is not None


def test_zero_repeat_of_group():
    m = rex.compile("(ab){0}c").match("c")
    assert m is not None
    assert m.group(1) is None


def test_newline_only_input():
    assert rex.compile(".*").fullmatch("\n") is None
    assert rex.compile(".*").fullmatch("") is not None
