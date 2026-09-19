"""Capturing / non-capturing / named groups, numbering and nesting."""

import pytest

import rex
from rex.errors import RegexError


def test_basic_captures():
    m = rex.compile(r"(\w+)@(\w+\.\w+)").search("mail bob@example.com x")
    assert m.group(1) == "bob"
    assert m.group(2) == "example.com"
    assert m.groups() == ("bob", "example.com")
    assert m.span(1) == (5, 8)
    assert m.span(2) == (9, 20)


def test_nested_groups_numbered_by_open_paren():
    m = rex.compile(r"((a)(b))").fullmatch("ab")
    assert m.groups() == ("ab", "a", "b")
    assert m.group(1) == "ab"
    assert m.group(2) == "a"
    assert m.group(3) == "b"


def test_non_capturing_group_consumes_no_index():
    p = rex.compile(r"(?:ab)(c)")
    m = p.fullmatch("abc")
    assert m.groups() == ("c",)
    assert m.group(1) == "c"


def test_named_group_access():
    p = rex.compile(r"(?P<year>\d{4})-(?P<month>\d{2})")
    m = p.search("2026-09")
    assert m.group("year") == "2026"
    assert m.group("month") == "09"
    assert m.groupdict() == {"year": "2026", "month": "09"}


def test_named_group_does_not_consume_numeric_index():
    # PRD: named groups do not occupy a numeric id.
    p = rex.compile(r"(?P<a>x)(y)")
    m = p.fullmatch("xy")
    assert m.group(1) == "y"
    assert m.group("a") == "x"
    # groups() still lists every group in opening-paren order.
    assert m.groups() == ("x", "y")


def test_unmatched_optional_group_is_none():
    m = rex.compile(r"(a)(b)?(c)").fullmatch("ac")
    assert m.group(1) == "a"
    assert m.group(2) is None
    assert m.group(3) == "c"
    assert m.groups() == ("a", None, "c")
    assert m.start(2) == -1 and m.end(2) == -1


def test_repeated_group_keeps_last_capture():
    m = rex.compile(r"(\w)(\d)?").search("a1 b2")
    assert m.groups() == ("a", "1")


def test_duplicate_named_group_is_error():
    with pytest.raises(RegexError) as exc:
        rex.compile(r"(?P<n>a)(?P<n>b)")
    assert exc.value.pos == 12
    assert "redefinition" in str(exc.value)


def test_bad_group_name():
    with pytest.raises(RegexError):
        rex.compile(r"(?P<1bad>x)")
    with pytest.raises(RegexError):
        rex.compile(r"(?P<n>x")


def test_groupindex_mapping():
    p = rex.compile(r"(?P<a>x)(y)(?P<b>z)")
    # Names are exposed in opening-paren order; numeric group ids only count
    # unnamed captures.
    assert set(p.groupindex) == {"a", "b"}
    assert p.groups_count == 1


def test_group_with_quantifier_captures_whole_match():
    m = rex.compile(r"(\d{3})-(\d{4})").search("call 555-1234 now")
    assert m.group(1) == "555"
    assert m.group(2) == "1234"
    assert m.span() == (5, 13)


def test_unknown_group_raises_index_error():
    m = rex.compile("(a)").fullmatch("a")
    with pytest.raises(IndexError):
        m.group(5)
    with pytest.raises(IndexError):
        m.group("missing")
