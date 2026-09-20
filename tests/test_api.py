"""Public API tests: compile/Pattern/Match surface, findall/finditer
semantics, flags, and boundary cases (empty pattern / empty input)."""

import types

import pytest

import datamask as dm


def test_compile_returns_pattern():
    p = dm.compile("abc")
    assert isinstance(p, dm.Pattern)
    assert p.pattern == "abc"
    assert p.groups == 0
    assert p.groupindex == {}


def test_compile_flags_combined():
    p = dm.compile("^abc$", dm.IGNORECASE | dm.MULTILINE)
    assert p.search("xx\nABC\nyy").group() == "ABC"


def test_compile_flag_aliases():
    assert dm.IGNORECASE == dm.I
    assert dm.MULTILINE == dm.M


def test_compile_non_string_raises():
    with pytest.raises(TypeError):
        dm.compile(123)


def test_default_max_steps():
    assert dm.compile("a").max_steps == 100_000_000
    assert dm.compile("a", max_steps=7).max_steps == 7


# ------------------------------------------------------------------- Match
def test_match_group_variants():
    m = dm.compile(r"(\d{4})-(\d{2})-(\d{2})").search("date 2026-09-20!")
    assert m.group() == "2026-09-20"
    assert m.group(0) == "2026-09-20"
    assert m.group(1) == "2026"
    assert m.group(2) == "09"
    assert m.group(3) == "20"
    assert m.group(1, 3) == ("2026", "20")
    assert m.groups() == ("2026", "09", "20")
    assert m[1] == "2026"


def test_match_named_groups():
    p = dm.compile(r"(?P<y>\d+)-(?P<m>\d+)")
    m = p.search("2026-09")
    assert p.groupindex == {"y": 1, "m": 2}
    assert m.group("y") == "2026"
    assert m.group("m") == "09"
    assert m.group(1) == "2026"
    with pytest.raises(IndexError):
        m.group("nope")


def test_match_group_index_errors():
    m = dm.compile("(a)").match("a")
    with pytest.raises(IndexError):
        m.group(2)
    with pytest.raises(IndexError):
        m.group(-1)


def test_match_span_start_end():
    m = dm.compile(r"(b+)").search("aabbbcc")
    assert m.span() == (2, 5)
    assert m.span(1) == (2, 5)
    assert m.start() == 2
    assert m.end() == 5
    assert m.start(1) == 2
    assert m.end(1) == 5


def test_unmatched_group_span_and_default():
    m = dm.compile("(a)|(b)").search("b")
    assert m.groups() == (None, "b")
    assert m.groups("X") == ("X", "b")
    assert m.span(1) == (-1, -1)
    assert m.group(1) is None


def test_match_attributes():
    p = dm.compile("x")
    m = p.search("axb")
    assert m.re is p
    assert m.string == "axb"
    assert "Match" in repr(m)


# -------------------------------------------------------------- findall
def test_findall_no_groups():
    assert dm.compile(r"\d+").findall("a1b22c333") == ["1", "22", "333"]


def test_findall_one_group():
    assert dm.compile(r"a(\d)").findall("a1a2b3") == ["1", "2"]


def test_findall_multiple_groups():
    assert dm.compile(r"(\w)(\d)").findall("a1b2") == [("a", "1"), ("b", "2")]


def test_findall_empty_matches():
    assert dm.compile("a*").findall("baa") == ["", "aa", ""]
    assert dm.compile("").findall("ab") == ["", "", ""]


def test_findall_no_match():
    assert dm.compile("z").findall("abc") == []


# -------------------------------------------------------------- finditer
def test_finditer_is_lazy_generator():
    it = dm.compile(r"\d").finditer("1 2 3")
    assert isinstance(it, types.GeneratorType)
    assert next(it).group() == "1"
    assert [m.group() for m in it] == ["2", "3"]


def test_finditer_spans():
    spans = [m.span() for m in dm.compile("ab").finditer("abxxab")]
    assert spans == [(0, 2), (4, 6)]


def test_finditer_empty_match_progresses():
    matches = list(dm.compile("a*").finditer("baa"))
    assert [m.span() for m in matches] == [(0, 0), (1, 3), (3, 3)]


def test_finditer_multiline_anchors():
    text = "ab\ncd\nef"
    got = [m.group() for m in dm.compile("^..", dm.MULTILINE).finditer(text)]
    assert got == ["ab", "cd", "ef"]


# ------------------------------------------------- empty pattern / input
def test_empty_pattern():
    p = dm.compile("")
    assert p.search("abc").span() == (0, 0)
    assert p.match("abc").span() == (0, 0)
    assert p.fullmatch("") is not None
    assert p.fullmatch("a") is None


def test_empty_input():
    assert dm.compile("a").search("") is None
    assert dm.compile("a*").search("").span() == (0, 0)
    assert dm.compile("").search("").span() == (0, 0)
    assert dm.compile("a*").fullmatch("") is not None
    assert dm.compile("^$").search("") is not None


def test_search_pos_argument():
    p = dm.compile("a")
    assert p.search("aaa", 1).span() == (1, 2)
    assert p.search("aaa", 3) is None


def test_match_is_anchored_but_not_full():
    p = dm.compile("ab")
    assert p.match("abc").span() == (0, 2)
    assert p.match("xab") is None
