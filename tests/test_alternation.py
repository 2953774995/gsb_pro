"""Alternation precedence and left-to-right preference."""

import rex


def test_simple_alternation():
    p = rex.compile("cat|dog|bird")
    assert p.findall("cat dog bird fish") == ["cat", "dog", "bird"]


def test_leftmost_alternative_preferred():
    # Alternatives are tried left to right even when a later one is longer.
    m = rex.compile("a|ab").search("ab")
    assert m.group() == "a"
    m = rex.compile("ab|abc").search("abcd")
    assert m.group() == "ab"


def test_alternation_precedence_lower_than_concat():
    p = rex.compile("ab|cd")
    assert p.search("xcd").group() == "cd"
    assert p.search("xab").group() == "ab"
    assert rex.compile("a|b|c").fullmatch("b") is not None


def test_alternation_with_groups():
    p = rex.compile(r"(https?|ftp)://(\w+)")
    m = p.search("see https://example here")
    assert m.group(1) == "https"
    assert m.group(2) == "example"


def test_alternation_empty_branch():
    assert rex.compile("a|").findall("a") == ["a", ""]
    p = rex.compile("(a|)x")
    assert p.fullmatch("x") is not None
    m = p.fullmatch("ax")
    assert m.group(1) == "a"


def test_alternation_backtracking_restores_captures():
    # The first alternative captures then fails; its capture must be reset so
    # the successful alternative's captures are the only visible ones.
    m = rex.compile(r"(abc|x)(def|y)").fullmatch("xy")
    assert m.groups() == ("x", "y")
    m = rex.compile(r"(a)|(b)").search("b")
    assert m.groups() == (None, "b")
    m = rex.compile(r"(a)|(b)").search("a")
    assert m.groups() == ("a", None)
