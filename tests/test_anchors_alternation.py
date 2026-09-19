"""Anchors, Multiline semantics, IgnoreCase and alternation."""

import rex


def test_anchor_default_single_line():
    text = "abc\ndef"
    assert rex.compile("^def").search(text) is None
    assert rex.compile("abc$").search(text) is None
    assert rex.compile("^abc").search(text) is not None
    assert rex.compile("def$").search(text) is not None


def test_multiline_caret():
    text = "abc\ndef\nghi"
    p = rex.compile("^def", rex.MULTILINE)
    assert p.search(text).span() == (4, 7)
    assert rex.compile("^[a-z]+", rex.MULTILINE).findall(text) == [
        "abc", "def", "ghi",
    ]


def test_multiline_dollar_matches_before_newline():
    text = "abc\ndef"
    p = rex.compile("abc$", rex.MULTILINE)
    assert p.search(text).span() == (0, 3)
    assert rex.compile("def$", rex.MULTILINE).search(text).span() == (4, 7)
    spans = [m.span() for m in rex.compile("$", rex.MULTILINE).finditer("a\nb\n")]
    assert spans == [(1, 1), (3, 3), (4, 4)]


def test_multiline_caret_positions():
    spans = [m.span() for m in rex.compile("^", rex.MULTILINE).finditer("a\nb")]
    assert spans == [(0, 0), (2, 2)]


def test_dollar_without_multiline_only_at_end():
    assert rex.compile("a$").search("a\na") is not None
    assert rex.compile("a$").search("a\na").span() == (2, 3)


def test_ignorecase():
    assert rex.compile("abc", rex.IGNORECASE).match("ABC") is not None
    assert rex.compile("abc", rex.IGNORECASE).match("aBc") is not None
    assert rex.compile("ABC", rex.IGNORECASE).match("abc") is not None
    assert rex.compile("abc").match("ABC") is None
    assert rex.compile("[a-z]+", rex.IGNORECASE).match("HELLO").group() == "HELLO"
    assert rex.compile("i", rex.IGNORECASE | rex.MULTILINE).findall("I\ni") == ["I", "i"]


def test_alternation_left_to_right():
    assert rex.compile("a|ab").match("ab").group() == "a"
    assert rex.compile("ab|a").match("ab").group() == "ab"
    assert rex.compile("cat|caterpillar").match("caterpillar").group() == "cat"


def test_alternation_backtracks_into_later_branches():
    assert rex.compile("(a|ab)(c|bcd)").match("abcd").groups() == ("a", "bcd")
    assert rex.compile("a|b|c").match("c").group() == "c"


def test_alternation_empty_branches():
    assert rex.compile("a|").match("").group() == ""
    assert rex.compile("|a").match("").group() == ""
    assert rex.compile("(|a)b").match("ab").group(1) == "a"


def test_alternation_precedence():
    # "ab|cd" is (ab)|(cd), not a(b|c)d
    p = rex.compile("ab|cd")
    assert p.match("ab") is not None
    assert p.match("cd") is not None
    assert p.match("ad") is None
    # concatenation binds tighter than alternation
    assert rex.compile("xy|z").match("xy") is not None
    assert rex.compile("xy|z").match("xz") is None


def test_alternation_with_groups():
    m = rex.compile("x(a|b)y").match("xby")
    assert m.group(1) == "b"
