"""Alternation: left-to-right preference, precedence, empty branches."""
import rex


def test_leftmost_branch_preferred():
    assert rex.compile("a|ab").search("ab").group() == "a"
    assert rex.compile("ab|a").search("ab").group() == "ab"


def test_shorter_prefix_wins_even_if_longer_exists():
    assert rex.compile("cat|cater").search("caterpillar").group() == "cat"
    assert rex.compile("cater|cat").search("caterpillar").group() == "cater"


def test_alternation_binds_looser_than_concat():
    # "ab|cd" means (ab)|(cd), not a(b|c)d
    p = rex.compile("ab|cd")
    assert p.fullmatch("ab") is not None
    assert p.fullmatch("cd") is not None
    assert p.fullmatch("ad") is None


def test_multi_branch():
    p = rex.compile("a|b|c")
    assert p.search("zc").group() == "c"
    assert p.fullmatch("b") is not None


def test_empty_branch_matches_empty():
    m = rex.compile("a|").search("bbb")
    assert m.group() == ""
    assert m.span() == (0, 0)


def test_trailing_bar_is_empty_branch():
    assert rex.compile("abc|").fullmatch("abc") is not None
    assert rex.compile("abc|").fullmatch("") is not None


def test_alternation_with_anchors():
    p = rex.compile("^a|b$")
    assert p.search("aXX") is not None
    assert p.search("XXb") is not None
    assert p.search("XaX") is None


def test_alternation_backtracking_into_branches():
    # first branch matches "a" but then "c" fails -> try second branch
    m = rex.compile("(?:ab|a)c").search("ac")
    assert m.group() == "ac"
