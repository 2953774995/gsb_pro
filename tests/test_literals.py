"""Literals, dot and escape sequences."""

import pytest

import regexlab
from regexlab import RegexError


def test_plain_literal_match():
    m = regexlab.match("abc", "abcdef")
    assert m is not None
    assert m.group(0) == "abc"
    assert m.span() == (0, 3)


def test_literal_no_match():
    assert regexlab.match("abc", "abd") is None


def test_match_is_anchored_at_start():
    assert regexlab.match("bc", "abc") is None
    assert regexlab.search("bc", "abc") is not None


def test_dot_matches_any_char_but_newline():
    assert regexlab.match("a.c", "abc") is not None
    assert regexlab.match("a.c", "a\nc") is None


@pytest.mark.parametrize("escape,matching,non_matching", [
    (r"\d", "7", "a"),
    (r"\D", "a", "7"),
    (r"\w", "z", "-"),
    (r"\w", "_", " "),
    (r"\W", "-", "z"),
    (r"\s", " ", "x"),
    (r"\s", "\t", "x"),
    (r"\S", "x", " "),
])
def test_predefined_classes(escape, matching, non_matching):
    assert regexlab.fullmatch(escape, matching) is not None
    assert regexlab.fullmatch(escape, non_matching) is None


@pytest.mark.parametrize("escape,char", [
    (r"\n", "\n"), (r"\t", "\t"), (r"\r", "\r"),
    (r"\f", "\f"), (r"\v", "\v"),
])
def test_control_character_escapes(escape, char):
    assert regexlab.fullmatch(escape, char) is not None


@pytest.mark.parametrize("escaped", list(".*+?^$()[]{}|\\"))
def test_escaped_metacharacters_are_literal(escaped):
    pattern = "\\" + escaped
    assert regexlab.fullmatch(pattern, escaped) is not None
    # and it must NOT act as the metacharacter
    assert regexlab.fullmatch(pattern, "x") is None


def test_backslash_at_end_is_error():
    with pytest.raises(RegexError):
        regexlab.compile("abc\\")


def test_unknown_letter_escape_is_error():
    with pytest.raises(RegexError):
        regexlab.compile(r"\q")
