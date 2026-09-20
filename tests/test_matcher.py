"""Matching-engine semantics: literals, classes, quantifiers, groups,
anchors, alternation, flags, and catastrophic-backtracking protection."""

import time

import pytest

import datamask as dm


# ------------------------------------------------------------------ basics
def test_literal_search_match_fullmatch():
    p = dm.compile("abc")
    assert p.search("xxabcxx").span() == (2, 5)
    assert p.match("abcdef").span() == (0, 3)
    assert p.match("xabc") is None
    assert p.fullmatch("abc") is not None
    assert p.fullmatch("abcd") is None


def test_dot_does_not_match_newline():
    assert dm.compile("a.b").search("a\nb") is None
    assert dm.compile("a.b").search("axb").group() == "axb"


def test_dot_star_stays_on_one_line():
    m = dm.compile("a.*").search("a12\na34")
    assert m.group() == "a12"


def test_empty_pattern_matches_empty():
    p = dm.compile("")
    assert p.search("abc").span() == (0, 0)
    assert p.fullmatch("") is not None
    assert p.fullmatch("a") is None


def test_empty_input():
    assert dm.compile("a").search("") is None
    assert dm.compile("a*").search("").span() == (0, 0)
    assert dm.compile("").search("") is not None


def test_star_matches_zero_times():
    assert dm.compile("ab*c").match("ac").group() == "ac"


# ------------------------------------------------------------- char classes
@pytest.mark.parametrize(
    "pattern,text,expected",
    [
        ("[abc]", "xbx", "b"),
        ("[^abc]", "abd", "d"),
        ("[a-z]", "1q2", "q"),
        ("[a-z0-9]+", "ab12", "ab12"),
        (r"\d+", "ab123", "123"),
        (r"\D+", "  12", "  "),
        (r"\w+", "_ab9 ", "_ab9"),
        (r"\W+", "ab !", " !"),
        (r"\s+", "a \t b", " \t "),
        (r"\S+", " ab", "ab"),
        ("[]]+", "a]]b", "]]"),
        ("[^]]+", "]ab]", "ab"),
    ],
)
def test_classes(pattern, text, expected):
    assert dm.compile(pattern).search(text).group() == expected


def test_negated_class_excludes_all_members():
    p = dm.compile("[^xyz]")
    assert p.search("xyz") is None
    assert p.search("xya").group() == "a"


# --------------------------------------------------------------- quantifiers
def test_greedy_vs_lazy():
    assert dm.compile("a+").search("aaa").group() == "aaa"
    assert dm.compile("a+?").search("aaa").group() == "a"
    assert dm.compile("a*?").search("aaa").group() == ""
    assert dm.compile("<.+>").search("<a><b>").group() == "<a><b>"
    assert dm.compile("<.+?>").search("<a><b>").group() == "<a>"


def test_brace_repeat_counts():
    assert dm.compile("a{3}").fullmatch("aaa") is not None
    assert dm.compile("a{3}").fullmatch("aa") is None
    assert dm.compile("a{2,}").fullmatch("aaaa") is not None
    assert dm.compile("a{2,}").fullmatch("a") is None
    assert dm.compile("a{2,4}").fullmatch("aaa") is not None
    assert dm.compile("a{2,4}").fullmatch("aaaaa") is None
    assert dm.compile("a{2,4}").search("aaaaa").group() == "aaaa"


def test_lazy_brace_repeat():
    assert dm.compile("a{2,4}?").search("aaaa").group() == "aa"


def test_optional_zero_or_one():
    p = dm.compile("colou?r")
    assert p.fullmatch("color") is not None
    assert p.fullmatch("colour") is not None
    assert p.fullmatch("colouur") is None


def test_empty_loop_terminates():
    # (a*)* and friends must not hang the VM.
    assert dm.compile("(a*)*").search("aaa").span() == (0, 3)
    assert dm.compile("()*").search("x").span() == (0, 0)
    assert dm.compile("(a|)*").search("aa").span() == (0, 2)
    assert dm.compile("(?:a?)+").search("aa").span() == (0, 2)


# -------------------------------------------------------------- alternation
def test_alternation_left_to_right_preference():
    assert dm.compile("a|ab").search("ab").group() == "a"
    assert dm.compile("ab|a").search("ab").group() == "ab"
    assert dm.compile("(a|ab)(c|bcd)").match("abcd").group() == "abcd"


def test_alternation_backtracks_to_next_branch():
    assert dm.compile("(a|ab)c").match("abc").group() == "abc"


# ------------------------------------------------------------------- groups
def test_group_numbering_by_left_paren():
    m = dm.compile("(a)(b)(c)").match("abc")
    assert m.group(1) == "a"
    assert m.group(2) == "b"
    assert m.group(3) == "c"
    assert m.groups() == ("a", "b", "c")


def test_nested_groups():
    m = dm.compile("((a)(b))").match("ab")
    assert m.group(1) == "ab"
    assert m.group(2) == "a"
    assert m.group(3) == "b"


def test_named_group_access():
    m = dm.compile(r"(?P<year>\d{4})-(?P<month>\d{2})").search("2026-09")
    assert m.group("year") == "2026"
    assert m.group("month") == "09"
    assert m.group(1) == "2026"


def test_nonparticipating_group_is_none():
    m = dm.compile("(a)|(b)").search("b")
    assert m.group(1) is None
    assert m.group(2) == "b"
    assert m.groups() == (None, "b")
    assert m.span(1) == (-1, -1)


def test_group_in_repeat_keeps_last_iteration():
    m = dm.compile("(ab)+").match("ababab")
    assert m.group(1) == "ab"
    m = dm.compile(r"(\d){3}").match("123")
    assert m.group(1) == "3"


# ------------------------------------------------------------- anchors/flags
def test_anchors_default():
    p = dm.compile("^abc$")
    assert p.fullmatch("abc") is not None
    assert p.search("abc") is not None
    assert p.search("xabc") is None
    assert p.search("abc\n") is None  # strict $: only end of string


def test_multiline_anchors():
    text = "ab\ncd\nef"
    assert [m.group() for m in dm.compile("^..", dm.MULTILINE).finditer(text)] == [
        "ab", "cd", "ef",
    ]
    m = dm.compile("cd$", dm.MULTILINE).search(text)
    assert m.span() == (3, 5)
    # $ matches before a newline in multiline mode
    m = dm.compile("ab$", dm.MULTILINE).search(text)
    assert m.span() == (0, 2)
    # without MULTILINE, ^ only matches at position 0
    assert dm.compile("^cd").search(text) is None


def test_ignorecase():
    assert dm.compile("abc", dm.IGNORECASE).search("xxAbC").group() == "AbC"
    assert dm.compile("[a-z]+", dm.IGNORECASE).match("AbC").group() == "AbC"
    assert dm.compile("[^a-z]", dm.IGNORECASE).search("A!").group() == "!"
    assert dm.compile("ABC").search("abc") is None


# ------------------------------------------- catastrophic backtracking guard
def test_catastrophic_backtracking_fails_fast():
    p = dm.compile("(a+)+$", max_steps=100_000)
    start = time.monotonic()
    with pytest.raises(dm.PatternTimeoutError):
        p.search("a" * 25 + "b")
    elapsed = time.monotonic() - start
    assert elapsed < 5.0


def test_timeout_is_a_pattern_error():
    p = dm.compile("(a|a)*$", max_steps=10_000)
    with pytest.raises(dm.PatternError):
        p.search("a" * 18 + "!")


def test_default_max_steps_is_100m():
    assert dm.compile("a").max_steps == 100_000_000


def test_step_budget_shared_across_search_positions():
    # The budget covers the whole search() call, not each start position.
    p = dm.compile("(a+)+$", max_steps=50_000)
    with pytest.raises(dm.PatternTimeoutError):
        p.search("a" * 30 + "!")


def test_pathological_pattern_still_matches_quickly_when_ok():
    p = dm.compile("(a+)+$")
    assert p.match("a" * 200).group() == "a" * 200
