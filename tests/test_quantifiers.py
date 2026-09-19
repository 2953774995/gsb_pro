"""Quantifiers: greedy vs lazy, counted repeats, repeat-related errors."""

import pytest

import regexlab
from regexlab import RegexError


def test_star():
    assert regexlab.match("ab*c", "ac").group(0) == "ac"
    assert regexlab.match("ab*c", "abbbc").group(0) == "abbbc"


def test_plus_requires_one():
    assert regexlab.match("ab+c", "ac") is None
    assert regexlab.match("ab+c", "abc").group(0) == "abc"


def test_question_mark():
    assert regexlab.fullmatch("colou?r", "color") is not None
    assert regexlab.fullmatch("colou?r", "colour") is not None
    assert regexlab.fullmatch("colou?r", "colouur") is None


@pytest.mark.parametrize("pattern,text,expected", [
    ("a{3}", "aaaa", "aaa"),
    ("a{2,}", "aaaaa", "aaaaa"),
    ("a{2,4}", "aaaaa", "aaaa"),
    ("a{,3}", "aaaaa", "aaa"),
    ("a{0}", "aaa", ""),
])
def test_counted_repeats(pattern, text, expected):
    assert regexlab.match(pattern, text).group(0) == expected


def test_counted_repeat_exact_fullmatch():
    assert regexlab.fullmatch(r"\d{4}", "1234") is not None
    assert regexlab.fullmatch(r"\d{4}", "123") is None
    assert regexlab.fullmatch(r"\d{4}", "12345") is None


def test_greedy_takes_as_much_as_possible():
    m = regexlab.match("a.*b", "axbxb")
    assert m.group(0) == "axbxb"


def test_lazy_takes_as_little_as_possible():
    m = regexlab.match("a.*?b", "axbxb")
    assert m.group(0) == "axb"


def test_greedy_and_lazy_differ_on_same_input():
    greedy = regexlab.match("a.*b", "axbxb").group(0)
    lazy = regexlab.match("a.*?b", "axbxb").group(0)
    assert greedy != lazy


@pytest.mark.parametrize("pattern,expected", [
    ("a+?", "a"),
    ("ab??", "a"),
    ("a{2,4}?", "aa"),
])
def test_lazy_variants(pattern, expected):
    assert regexlab.match(pattern, "aaaa").group(0) == expected


def test_lazy_star_still_finds_a_match():
    m = regexlab.search("<.*?>", "<a><b>")
    assert m.group(0) == "<a>"


def test_greedy_backtracks_to_allow_overall_match():
    m = regexlab.match(r"\d+1", "1231")
    assert m is not None
    assert m.group(0) == "1231"


def test_empty_body_repeat_terminates():
    # (a*)* must not loop forever; the empty-iteration guard kicks in.
    m = regexlab.match("(a*)*", "aa")
    assert m is not None
    assert m.group(0) == "aa"


def test_dangling_quantifiers_are_errors():
    for pattern in ("*a", "+a", "?a", "{2}a", "a{1}{2}"):
        with pytest.raises(RegexError):
            regexlab.compile(pattern)


def test_multiple_repeat_is_error():
    for pattern in ("a**", "a*+", "a?*", "a*{2}", "a{2}*"):
        with pytest.raises(RegexError):
            regexlab.compile(pattern)


def test_lazy_marker_is_not_multiple_repeat():
    # *? +? ?? {m,n}? are single (lazy) quantifiers and must compile.
    for pattern in ("a*?", "a+?", "a??", "a{1,3}?"):
        regexlab.compile(pattern)


def test_min_greater_than_max_is_error():
    with pytest.raises(RegexError):
        regexlab.compile("a{3,2}")


def test_bad_brace_contents_are_literal():
    # "{x}" is not quantifier syntax, so it is a literal string.
    assert regexlab.fullmatch("a{x}", "a{x}") is not None


def test_quantifying_anchor_is_error():
    for pattern in ("^*", "$+", r"\b?"):
        with pytest.raises(RegexError):
            regexlab.compile(pattern)
