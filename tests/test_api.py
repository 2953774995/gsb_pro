"""Pattern/Match object API: search/match/fullmatch/findall/finditer."""
import types

import pytest

import rex


def test_compile_returns_pattern():
    p = rex.compile("abc")
    assert isinstance(p, rex.Pattern)
    assert p.pattern == "abc"
    assert p.flags == 0


def test_compile_rejects_non_string():
    with pytest.raises(TypeError):
        rex.compile(123)


def test_search_finds_leftmost():
    m = rex.compile("a+").search("bbbaaacc")
    assert m.span() == (3, 6)


def test_search_pos_argument():
    p = rex.compile("a+")
    assert p.search("aabaa", pos=3).span() == (3, 5)


def test_match_pos_argument():
    p = rex.compile("b+")
    assert p.match("aabb", pos=2).span() == (2, 4)
    assert p.match("aabb") is None


def test_match_object_attributes():
    p = rex.compile("b+")
    m = p.search("aabbc")
    assert m.re is p
    assert m.string == "aabbc"
    assert m.pos == 2
    assert repr(m).startswith("<rex.Match")


def test_group_zero_is_whole_match():
    m = rex.compile("(a)(b)").match("ab")
    assert m.group() == "ab"
    assert m.group(0) == "ab"
    assert m.group(1, 2) == ("a", "b")
    assert m.group(0, 2) == ("ab", "b")


def test_span_start_end_defaults():
    m = rex.compile("bc").search("abcd")
    assert m.span() == (1, 3)
    assert m.start() == 1
    assert m.end() == 3


def test_findall_no_groups_returns_whole_matches():
    assert rex.compile(r"\d+").findall("a1b22c333") == ["1", "22", "333"]
    assert rex.compile("z").findall("abc") == []


def test_findall_one_group_returns_group():
    assert rex.compile(r"(\d)+").findall("a12b3") == ["2", "3"]
    assert rex.compile(r"x(\d+)y").findall("x1y x22y") == ["1", "22"]


def test_findall_multiple_groups_returns_tuples():
    p = rex.compile(r"(\w+)=(\w+)")
    assert p.findall("a=1 b=2") == [("a", "1"), ("b", "2")]


def test_finditer_is_lazy_generator():
    it = rex.compile(r"\d").finditer("1a2b3")
    assert isinstance(it, types.GeneratorType)
    assert next(it).group() == "1"
    assert next(it).group() == "2"
    rest = list(it)
    assert [m.group() for m in rest] == ["3"]


def test_finditer_spans_and_empty_matches():
    spans = [m.span() for m in rex.compile("a*").finditer("baa")]
    assert spans == [(0, 0), (1, 3), (3, 3)]


def test_finditer_empty_pattern():
    spans = [m.span() for m in rex.compile("").finditer("ab")]
    assert spans == [(0, 0), (1, 1), (2, 2)]


def test_finditer_empty_input():
    assert [m.span() for m in rex.compile("a*").finditer("")] == [(0, 0)]
    assert list(rex.compile("a+").finditer("")) == []


def test_findall_empty_pattern():
    assert rex.compile("").findall("ab") == ["", "", ""]


def test_pattern_groups_and_groupindex():
    p = rex.compile(r"(?P<a>x)(y)(?P<b>z)")
    assert p.groups == 1
    assert set(p.groupindex) == {"a", "b"}
