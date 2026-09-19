"""findall / finditer iteration semantics and empty-pattern boundaries."""

import re

import pytest

import rex


def test_finditer_is_lazy():
    p = rex.compile(r"\d+")
    iterator = p.finditer("a1 b2 c3 d4")
    first = next(iterator)
    assert first.group() == "1"
    assert first.start() == 1 and first.end() == 2
    second = next(iterator)
    assert second.group() == "2"
    rest = [m.group() for m in iterator]
    assert rest == ["3", "4"]


def test_finditer_no_matches():
    assert list(rex.compile(r"\d+").finditer("abc def")) == []


def test_findall_no_groups():
    assert rex.compile(r"\d+").findall("a1 b22") == ["1", "22"]


def test_findall_single_group_returns_string():
    assert rex.compile(r"(\d+)").findall("a1 b22") == ["1", "22"]


def test_findall_multiple_groups_returns_tuples():
    p = rex.compile(r"(\w+)=(\d+)")
    assert p.findall("a=1 b=22") == [("a", "1"), ("b", "22")]


def test_findall_non_participating_group_empty_string():
    assert rex.compile(r"(ab)*").findall("abc") == ["ab", "", ""]
    assert rex.compile(r"(a)|(b)").findall("ab") == [("a", ""), ("", "b")]


def test_empty_pattern_matches_every_gap():
    p = rex.compile("")
    assert [m.span() for m in p.finditer("abc")] == [(0, 0), (1, 1), (2, 2), (3, 3)]
    assert p.findall("abc") == ["", "", "", ""]


def test_empty_text():
    assert rex.compile("a").search("") is None
    assert rex.compile("a").findall("") == []
    m = rex.compile("").search("")
    assert m is not None and m.span() == (0, 0)
    assert rex.compile("").findall("") == [""]


def test_empty_group():
    m = rex.compile("()").fullmatch("")
    assert m.groups() == ("",)
    assert m.span(1) == (0, 0)


def test_empty_pattern_with_flags_and_captures():
    p = rex.compile("(?:)", rex.MULTILINE)
    assert len(p.findall("\n\n")) == 3


def test_match_object_api():
    m = rex.compile(r"(\w)(\d)").search("xx a1 yy")
    assert m.group() == "a1"
    assert m.group(0) == "a1"
    assert m.group(1, 2) == ("a", "1")
    assert m.groups() == ("a", "1")
    assert m.span() == (3, 5)
    assert m.start(2) == 4
    assert m.string == "xx a1 yy"
    assert m[1] == "a"


def test_match_and_fullmatch_pos_anchoring():
    p = rex.compile("abc")
    assert p.match("xxabc", pos=2).group() == "abc"
    assert p.match("xxabc", pos=1) is None
    assert p.fullmatch("xxabc", pos=2) is not None
    assert p.fullmatch("xxabcd", pos=2) is None


def test_endpos_limits_search():
    p = rex.compile("abc")
    assert p.search("xxabc", endpos=4) is None
    assert p.search("xxabc", endpos=5) is not None


def test_finditer_overlapping_empty_parity_with_re():
    cases = [
        ("a*", "baba"),
        ("a*", "aaa"),
        ("", "abc"),
        ("x?", "aaa"),
        (r"\d*", "a12b3"),
        ("a*?", "baba"),
    ]
    for pat, text in cases:
        assert [m.span() for m in rex.compile(pat).finditer(text)] == [
            m.span() for m in re.finditer(pat, text)
        ]
        assert rex.compile(pat).findall(text) == re.findall(pat, text)


def test_iteration_does_not_mutate_previous_matches():
    p = rex.compile(r"(\d)")
    matches = list(p.finditer("123"))
    assert [m.group(1) for m in matches] == ["1", "2", "3"]
    assert matches[0].group(1) == "1"


def test_compile_accepts_pattern_object():
    p = rex.compile("a+")
    assert rex.compile(p) is p


def test_type_errors():
    with pytest.raises(TypeError):
        rex.compile(123)
    with pytest.raises(TypeError):
        rex.compile("a").search(123)
