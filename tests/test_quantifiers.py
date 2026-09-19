"""Quantifiers: *, +, ?, {m}, {m,}, {m,n} and lazy variants."""
import pytest

import rex


def test_star_allows_zero():
    m = rex.compile("ab*c").search("ac")
    assert m.group() == "ac"


def test_star_greedy():
    assert rex.compile("ab*").search("abbb").group() == "abbb"
    assert rex.compile("a*").search("aaa").group() == "aaa"


def test_plus_requires_one():
    assert rex.compile("ab+c").search("ac") is None
    assert rex.compile("ab+c").search("abbbc").group() == "abbbc"


def test_question_optional():
    assert rex.compile("colou?r").match("color") is not None
    assert rex.compile("colou?r").match("colour") is not None
    assert rex.compile("ab?").search("a").group() == "a"


def test_exact_count():
    p = rex.compile("a{3}")
    assert p.search("aaaa").group() == "aaa"
    assert p.search("aa") is None
    assert p.fullmatch("aaa") is not None
    assert p.fullmatch("aaaa") is None


def test_min_count():
    p = rex.compile("a{2,}")
    assert p.search("aaaa").group() == "aaaa"
    assert p.search("a") is None


def test_min_max_count():
    p = rex.compile("a{2,4}")
    assert p.search("aaaaaa").group() == "aaaa"
    assert p.search("aa").group() == "aa"
    assert p.search("a") is None


def test_zero_count():
    m = rex.compile("a{0}").search("aaa")
    assert m.group() == ""
    assert m.span() == (0, 0)


def test_zero_to_n():
    assert rex.compile("a{0,2}").search("aaaa").group() == "aa"
    assert rex.compile("a{0,2}").search("b").group() == ""


def test_max_repeat_boundary_ok():
    assert rex.compile("a{1,65535}") is not None
    assert rex.compile("a{65535}") is not None


def test_max_repeat_too_large():
    with pytest.raises(rex.RegexError, match="too large"):
        rex.compile("a{1,65536}")
    with pytest.raises(rex.RegexError, match="too large"):
        rex.compile("a{65536}")


def test_min_greater_than_max():
    with pytest.raises(rex.RegexError, match="min repeat greater"):
        rex.compile("a{3,2}")


def test_lazy_star():
    assert rex.compile("a*?").search("aaa").group() == ""
    assert rex.compile("a*?b").search("aab").group() == "aab"


def test_lazy_plus():
    assert rex.compile("a+?").search("aaa").group() == "a"


def test_lazy_question():
    m = rex.compile("ab??").search("ab")
    assert m.group() == "a"  # prefers zero occurrences of "b"


def test_lazy_brace():
    assert rex.compile("a{2,4}?").search("aaaa").group() == "aa"
    assert rex.compile("a{2,}?").search("aaaa").group() == "aa"


def test_lazy_dot_star_extracts_first_tag():
    text = "<a><b>"
    assert rex.compile("<.*?>").search(text).group() == "<a>"
    assert rex.compile("<.*>").search(text).group() == "<a><b>"


def test_greedy_backtracks_to_allow_overall_match():
    m = rex.compile("a.*b").search("axbxb")
    assert m.group() == "axbxb"
    m = rex.compile("a.*?b").search("axbxb")
    assert m.group() == "axb"


def test_quantifier_on_group():
    assert rex.compile("(ab){2,3}").fullmatch("ababab") is not None
    assert rex.compile("(ab){2,3}").fullmatch("abab") is not None
    assert rex.compile("(ab){2,3}").fullmatch("ab") is None
    assert rex.compile("(ab){2,3}").fullmatch("abababab") is None


def test_nothing_to_repeat():
    for pat in ["*abc", "+abc", "?abc", "a**", "a*+", "{2}a"]:
        with pytest.raises(rex.RegexError, match="nothing to repeat"):
            rex.compile(pat), pat


def test_cannot_quantify_anchor():
    with pytest.raises(rex.RegexError, match="anchor"):
        rex.compile("^*")
    with pytest.raises(rex.RegexError, match="anchor"):
        rex.compile("$+")


def test_long_input_star_no_recursion_error():
    # iterative repeat implementation must handle long inputs
    p = rex.compile("x*")
    assert p.fullmatch("x" * 50000) is not None
