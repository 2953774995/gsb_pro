"""Quantifiers: *, +, ?, {m}, {m,}, {m,n} and their lazy variants."""

import pytest

import rex


def test_star():
    p = rex.compile("a*")
    assert p.match("").group() == ""
    assert p.match("aaa").group() == "aaa"
    assert p.match("b").group() == ""


def test_plus():
    p = rex.compile("a+")
    assert p.match("aaa").group() == "aaa"
    assert p.match("") is None
    assert p.match("b") is None


def test_question():
    p = rex.compile("colou?r")
    assert p.match("color") is not None
    assert p.match("colour") is not None
    assert p.match("colouur") is None


def test_brace_exact():
    p = rex.compile("a{3}")
    assert p.match("aaa") is not None
    assert p.fullmatch("aaa") is not None
    assert p.fullmatch("aa") is None
    assert p.fullmatch("aaaa") is None


def test_brace_open_ended():
    p = rex.compile("a{2,}")
    assert p.match("aaaa").group() == "aaaa"
    assert p.match("aa") is not None
    assert p.match("a") is None


def test_brace_range():
    p = rex.compile("a{2,4}")
    assert p.match("aaaaa").group() == "aaaa"
    assert p.fullmatch("aa") is not None
    assert p.fullmatch("aaa") is not None
    assert p.fullmatch("aaaa") is not None
    assert p.fullmatch("a") is None
    assert p.fullmatch("aaaaa") is None


def test_brace_zero():
    assert rex.compile("a{0}").match("").group() == ""
    assert rex.compile("a{0,2}").match("aaa").group() == "aa"


def test_lazy_star():
    assert rex.compile("a*?").match("aaa").group() == ""
    assert rex.compile("<(.*?)>").search("<a><b>").group(1) == "a"


def test_lazy_plus():
    assert rex.compile("a+?").match("aaa").group() == "a"
    assert rex.compile("a+?b").match("aab").group() == "aab"


def test_lazy_question():
    assert rex.compile("a??").match("a").group() == ""
    assert rex.compile("a??b").match("ab").group() == "ab"


def test_lazy_brace():
    assert rex.compile("a{2,4}?").match("aaaa").group() == "aa"
    assert rex.compile("a{2,}?").match("aaaa").group() == "aa"


def test_greedy_backtracking():
    assert rex.compile("a+ab").match("aaab").group() == "aaab"
    assert rex.compile(".*c").match("abcabc").group() == "abcabc"


def test_bounds_out_of_order_raises():
    with pytest.raises(rex.RegexError) as excinfo:
        rex.compile("a{3,2}")
    assert "out of order" in str(excinfo.value)


def test_repeat_limit_raises():
    with pytest.raises(rex.RegexError):
        rex.compile("a{65536}")
    with pytest.raises(rex.RegexError):
        rex.compile("a{1,70000}")
    # the boundary itself is accepted
    assert rex.compile("a{65535}") is not None


def test_malformed_brace_raises():
    with pytest.raises(rex.RegexError):
        rex.compile("a{2x}")


def test_quantifier_without_target_raises():
    for pat in ["*a", "+a", "?a", "{2}a", "**"]:
        with pytest.raises(rex.RegexError):
            rex.compile(pat)


def test_quantifier_after_anchor_raises():
    with pytest.raises(rex.RegexError):
        rex.compile("^*")
    with pytest.raises(rex.RegexError):
        rex.compile("$+")


def test_literal_brace_when_not_a_quantifier():
    assert rex.compile("a{").match("a{") is not None
    assert rex.compile("a{,5}").match("a{,5}") is not None
    assert rex.compile("{").match("{") is not None
    assert rex.compile("}").match("}") is not None


def test_zero_width_repeat_terminates():
    # A repeated group that can match empty must not loop forever.
    assert rex.compile("(a?)*").match("").group() == ""
    assert rex.compile("(a*)+").match("").group() == ""
    assert rex.compile("(a?){2,3}").match("").group() == ""
    assert rex.compile("()*").match("").group() == ""
