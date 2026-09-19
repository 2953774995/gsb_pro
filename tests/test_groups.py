"""Groups, captures, alternation and nesting."""

import regexlab


def test_simple_capture():
    m = regexlab.match("(abc)", "abcdef")
    assert m.group(1) == "abc"
    assert m.groups() == ("abc",)


def test_multiple_groups_numbered_left_to_right():
    m = regexlab.match(r"(\d+)-(\d+)", "12-345")
    assert m.groups() == ("12", "345")
    assert m.group(1) == "12"
    assert m.group(2) == "345"
    assert m.group(0) == "12-345"


def test_nested_groups():
    m = regexlab.match("((a)(b))", "ab")
    assert m.groups() == ("ab", "a", "b")


def test_non_capturing_group_not_counted():
    p = regexlab.compile("(?:ab)(cd)")
    assert p.groups == 1
    m = p.match("abcd")
    assert m.groups() == ("cd",)


def test_group_with_quantifier():
    m = regexlab.match("(ab)+", "ababab")
    assert m.group(0) == "ababab"
    assert m.group(1) == "ab"  # last iteration wins


def test_alternation():
    assert regexlab.fullmatch("cat|dog", "cat") is not None
    assert regexlab.fullmatch("cat|dog", "dog") is not None
    assert regexlab.fullmatch("cat|dog", "cow") is None


def test_alternation_first_branch_preferred():
    m = regexlab.match("a|ab", "ab")
    assert m.group(0) == "a"


def test_alternation_backtracks_to_second_branch():
    m = regexlab.match("(a|ab)(c|bcd)", "abcd")
    assert m is not None
    assert m.groups() == ("a", "bcd")


def test_alternation_inside_group_capture():
    m = regexlab.match("(foo|bar)baz", "barbaz")
    assert m.group(1) == "bar"


def test_non_participating_group_is_none():
    m = regexlab.match("(a)|(b)", "a")
    assert m.group(1) == "a"
    assert m.group(2) is None
    assert m.groups() == ("a", None)


def test_groups_default_for_non_participating():
    m = regexlab.match("(a)|(b)", "b")
    assert m.groups(default="X") == ("X", "b")


def test_group_positions():
    m = regexlab.search("(b+)", "aabbcc")
    assert m.span(1) == (2, 4)
    assert m.start(1) == 2
    assert m.end(1) == 4


def test_empty_alternation_branch():
    m = regexlab.fullmatch("a(b|)", "a")
    assert m is not None
    assert m.group(1) == ""


def test_deeply_nested_alternation():
    p = regexlab.compile("((a|b)|(c(d|e)))")
    m = p.match("ce")
    assert m.groups() == ("ce", None, "ce", "e")
