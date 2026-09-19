"""Invalid patterns must raise RegexError with a useful message."""

import pytest

import regexlab
from regexlab import RegexError


@pytest.mark.parametrize("pattern", [
    "(",                # unclosed group
    ")",                # stray closing paren
    "(a",               # unclosed group after content
    "a)",               # stray closing paren after content
    "((a)",             # nested unclosed
    "(?:a",             # unclosed non-capturing group
])
def test_unbalanced_parentheses(pattern):
    with pytest.raises(RegexError):
        regexlab.compile(pattern)


@pytest.mark.parametrize("pattern", ["*", "+", "?", "{1}", "a**", "a+*"])
def test_dangling_or_repeated_quantifier(pattern):
    with pytest.raises(RegexError):
        regexlab.compile(pattern)


@pytest.mark.parametrize("pattern", ["[", "[a", "[^", "[z-a]", "[b-a]"])
def test_bad_character_class(pattern):
    with pytest.raises(RegexError):
        regexlab.compile(pattern)


@pytest.mark.parametrize("pattern", ["a{3,2}", "\\", "\\q", "\\1"])
def test_misc_bad_patterns(pattern):
    with pytest.raises(RegexError):
        regexlab.compile(pattern)


def test_unknown_group_extension():
    with pytest.raises(RegexError):
        regexlab.compile("(?P<x>a)")


def test_error_message_mentions_position():
    try:
        regexlab.compile("ab)")
    except RegexError as exc:
        assert "position" in str(exc)
        assert exc.pos == 2
    else:
        raise AssertionError("expected RegexError")


def test_error_is_exception_subclass():
    assert issubclass(RegexError, Exception)


def test_non_string_pattern_rejected():
    with pytest.raises(RegexError):
        regexlab.compile(123)
