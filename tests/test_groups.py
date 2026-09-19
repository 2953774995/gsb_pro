"""Groups: capturing, non-capturing, named and nested."""

import pytest

import rex


def test_basic_capture():
    m = rex.compile(r"(\w+)@(\w+)").search("mail alice@example!")
    assert m.group(0) == "alice@example"
    assert m.group(1) == "alice"
    assert m.group(2) == "example"
    assert m.groups() == ("alice", "example")
    assert m.span(1) == (5, 10)
    assert m.span(2) == (11, 18)
    assert m.start(1) == 5
    assert m.end(2) == 18


def test_group_numbering_is_left_paren_order():
    m = rex.compile("(a)(b(c))(d)").match("abcd")
    assert m.group(1) == "a"
    assert m.group(2) == "bc"
    assert m.group(3) == "c"
    assert m.group(4) == "d"
    assert m.groups() == ("a", "bc", "c", "d")


def test_nested_capture():
    m = rex.compile("((a+)(b+))+").match("aabb")
    assert m.group(1) == "aabb"
    assert m.group(2) == "aa"
    assert m.group(3) == "bb"


def test_non_capturing_group():
    p = rex.compile("(?:ab)+")
    assert p.groups == 0
    assert p.match("ababab").group() == "ababab"
    m = rex.compile("(?:a)(b)").match("ab")
    assert m.groups() == ("b",)


def test_named_group():
    m = rex.compile(r"(?P<year>\d{4})-(?P<month>\d{2})").search("2026-09")
    assert m.group("year") == "2026"
    assert m.group("month") == "09"
    assert m.groupdict() == {"year": "2026", "month": "09"}
    assert m.span("year") == (0, 4)


def test_named_groups_do_not_consume_numeric_indices():
    p = rex.compile(r"(a)(?P<x>b)(c)")
    assert p.groups == 2
    assert p.groupindex == {"x": 3}
    m = p.match("abc")
    assert m.group(1) == "a"
    assert m.group(2) == "c"
    assert m.group("x") == "b"
    assert m.groups() == ("a", "c")


def test_unmatched_group_is_none():
    m = rex.compile("(a)|(b)").match("a")
    assert m.group(1) == "a"
    assert m.group(2) is None
    assert m.groups() == ("a", None)
    assert m.span(2) == (-1, -1)


def test_group_multiple_args():
    m = rex.compile("(a)(b)").match("ab")
    assert m.group(1, 2) == ("a", "b")
    assert m.group() == "ab"


def test_group_in_repeat_keeps_last_iteration():
    m = rex.compile("(a){3}").match("aaa")
    assert m.group(1) == "a"
    m = rex.compile(r"(\w+)\s?").match("one ")
    assert m.group(1) == "one"


def test_empty_group():
    m = rex.compile("()").match("")
    assert m.group(1) == ""
    assert m.span(1) == (0, 0)


def test_duplicate_group_name_raises():
    with pytest.raises(rex.RegexError) as excinfo:
        rex.compile(r"(?P<n>a)(?P<n>b)")
    assert "duplicate" in str(excinfo.value)


def test_invalid_group_name_raises():
    with pytest.raises(rex.RegexError):
        rex.compile("(?P<1bad>a)")
    with pytest.raises(rex.RegexError):
        rex.compile("(?P<>a)")


def test_unknown_group_syntax_raises():
    with pytest.raises(rex.RegexError):
        rex.compile("(?=a)")
    with pytest.raises(rex.RegexError):
        rex.compile("(?i)a")


def test_bad_group_access_raises():
    m = rex.compile("(a)").match("a")
    with pytest.raises(IndexError):
        m.group(5)
    with pytest.raises(IndexError):
        m.group("nope")
