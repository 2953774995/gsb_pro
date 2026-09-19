"""Quantifier boundaries: zero/one/bounded counts and lazy variants."""

import re

import rex


def test_star_zero_or_more():
    p = rex.compile("ab*c")
    assert [m.group() for m in p.finditer("ac abc abbc x")] == ["ac", "abc", "abbc"]


def test_plus_requires_one():
    p = rex.compile("ab+c")
    assert p.search("ac") is None
    assert p.search("abc").group() == "abc"


def test_question_optional():
    p = rex.compile("colou?r")
    assert p.findall("color colour colouur") == ["color", "colour"]


def test_exact_bounded():
    p = rex.compile("a{3}")
    assert p.findall("a aa aaa aaaa") == ["aaa", "aaa"]


def test_bounded_range_greedy():
    p = rex.compile("a{2,3}")
    assert p.findall("a aa aaa aaaa aaaaa") == ["aa", "aaa", "aaa", "aaa", "aa"]
    assert p.fullmatch("aa") is not None
    assert rex.compile("a{2,3}").fullmatch("a") is None


def test_bounded_open_ended():
    assert rex.compile("a{2,}").findall("a aa aaaa") == ["aa", "aaaa"]
    assert rex.compile("a{2,}").search("a") is None


def test_zero_bounds_can_match_empty():
    assert rex.compile("a{0}").fullmatch("") is not None
    assert rex.compile("a{0,0}b").fullmatch("b") is not None
    assert rex.compile("x{0}").findall("abc") == ["", "", "", ""]


def test_greedy_takes_longest():
    assert rex.compile("a+").search("aaaa").group() == "aaaa"
    assert rex.compile("<.*>").search("<a><b>").group() == "<a><b>"


def test_lazy_variants_take_shortest():
    assert rex.compile("a+?").search("aaaa").group() == "a"
    assert rex.compile("a*?b").search("aaab").group() == "aaab"
    assert rex.compile("<.*?>").findall("<a><b>") == ["<a>", "<b>"]
    assert rex.compile("a??b").search("aab").group() == "ab"
    assert rex.compile("a{2,4}?").search("aaaaa").group() == "aa"


def test_lazy_finditer_empty_match_semantics():
    for pat, text in [
        ("a*?", "baba"),
        (r"\w*?", "x y"),
        ("a*?", "aaa"),
    ]:
        assert [m.span() for m in rex.compile(pat).finditer(text)] == [
            m.span() for m in re.finditer(pat, text)
        ]


def test_lazy_capture_restored_on_backtrack():
    m = rex.compile(r"(a+?)(a+)").fullmatch("aaaa")
    assert m.group(1) == "a"
    assert m.group(2) == "aaa"


def test_nested_quantifiers():
    assert rex.compile("(ab)+").findall("ab abab ababab") == ["ab", "ab", "ab"]
    m = rex.compile("(a(b)?)*").fullmatch("abab")
    assert m is not None
