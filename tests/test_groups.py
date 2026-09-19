"""Groups: numbered, nested, named, non-capturing, alternation."""
import pytest

import rex


def test_numbered_groups_in_paren_order():
    m = rex.compile("((a)(b))").match("ab")
    assert m.group(0) == "ab"
    assert m.group(1) == "ab"
    assert m.group(2) == "a"
    assert m.group(3) == "b"
    assert m.groups() == ("ab", "a", "b")


def test_group_spans():
    m = rex.compile("(a+)(b+)").match("aabb")
    assert m.span(1) == (0, 2)
    assert m.span(2) == (2, 4)
    assert m.start(2) == 2
    assert m.end(1) == 2


def test_unmatched_optional_group_is_none():
    m = rex.compile("(a)?b").match("b")
    assert m.group(1) is None
    assert m.groups() == (None,)
    assert m.groups("x") == ("x",)
    assert m.span(1) == (-1, -1)
    assert m.start(1) == -1
    assert m.end(1) == -1


def test_nested_repeated_group_captures_last_iteration():
    m = rex.compile("(ab|cd)+").fullmatch("abcdab")
    assert m.group(1) == "ab"


def test_non_capturing_group():
    p = rex.compile("(?:ab)+")
    assert p.fullmatch("ababab") is not None
    assert p.groups == 0
    m = rex.compile("(?:a)(b)").match("ab")
    assert m.group(1) == "b"
    assert m.groups() == ("b",)


def test_named_group_basic():
    m = rex.compile(r"(?P<word>\w+)").search("hi there")
    assert m.group("word") == "hi"
    assert m.span("word") == (0, 2)


def test_named_groups_do_not_take_numbers():
    p = rex.compile(r"(?P<year>\d{4})-(?P<month>\d{2})-(\d{2})")
    assert p.groups == 1  # only the unnamed group is numbered
    m = p.match("2024-01-15")
    assert m.group("year") == "2024"
    assert m.group("month") == "01"
    assert m.group(1) == "15"
    assert m.groups() == ("15",)
    assert m.groupdict() == {"year": "2024", "month": "01"}


def test_groupdict_default():
    m = rex.compile(r"(?P<a>x)?b").match("b")
    assert m.groupdict() == {"a": None}
    assert m.groupdict("-") == {"a": "-"}


def test_group_multiple_args():
    m = rex.compile(r"(\d+)-(\w+)").match("12-ab")
    assert m.group(1, 2) == ("12", "ab")
    assert m.group(0, 1) == ("12-ab", "12")


def test_group_index_out_of_range():
    m = rex.compile("(a)").match("a")
    with pytest.raises(IndexError):
        m.group(2)
    with pytest.raises(IndexError):
        m.group("nope")


def test_alternation_inside_group():
    p = rex.compile("(cat|dog)s?")
    assert p.match("cats").group(1) == "cat"
    assert p.match("dog").group(1) == "dog"
    assert p.match("bird") is None


def test_empty_group_matches_empty():
    m = rex.compile("()").match("abc")
    assert m.group(1) == ""
    assert m.span(1) == (0, 0)


def test_deeply_nested_groups():
    m = rex.compile("((((x))))").match("x")
    assert m.groups() == ("x", "x", "x", "x")
