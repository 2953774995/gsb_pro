"""Invalid patterns must raise RegexError with reason and column info."""
import pytest

import rex
from rex import RegexError


def check(pattern, reason, column):
    with pytest.raises(RegexError) as excinfo:
        rex.compile(pattern)
    msg = str(excinfo.value)
    assert reason in msg, msg
    assert "column {}".format(column) in msg, msg
    assert excinfo.value.pos == column - 1


def test_unclosed_group():
    check("(abc", "unclosed group", 1)
    check("a(b(c", "unclosed group", 4)


def test_unmatched_close_paren():
    check("a)", "unmatched ')'", 2)
    check(")", "unmatched ')'", 1)


def test_unterminated_class():
    check("[abc", "unterminated character class", 1)
    check("x[abc", "unterminated character class", 2)


def test_empty_class():
    with pytest.raises(RegexError):
        rex.compile("[]")
    with pytest.raises(RegexError):
        rex.compile("[^]")


def test_nothing_to_repeat():
    check("*abc", "nothing to repeat", 1)
    check("+abc", "nothing to repeat", 1)
    check("?abc", "nothing to repeat", 1)
    check("a**", "nothing to repeat", 3)
    check("a*+", "nothing to repeat", 3)
    check("|*", "nothing to repeat", 2)


def test_cannot_quantify_anchor():
    check("^*", "cannot quantify an anchor", 2)
    check("a$+", "cannot quantify an anchor", 3)
    check("^?", "cannot quantify an anchor", 2)


def test_unknown_escape():
    check(r"\q", r"unknown escape \q", 1)
    check(r"a\qb", r"unknown escape \q", 2)
    check(r"[\e]", r"unknown escape \e", 2)


def test_trailing_backslash():
    check("abc\\", "trailing backslash", 4)
    check("\\", "trailing backslash", 1)


def test_backreference_not_supported():
    check(r"(a)\1", "backreferences", 4)
    assert "not supported" in str(_err(r"\2"))


def _err(pattern):
    with pytest.raises(RegexError) as excinfo:
        rex.compile(pattern)
    return excinfo.value


def test_bad_brace_repeat():
    check("a{3,2}", "min repeat greater than max repeat", 2)
    check("a{1,65536}", "repeat count too large", 2)
    check("a{65536}", "repeat count too large", 2)
    check("a{70000,}", "repeat count too large", 2)


def test_brace_repeat_boundaries_ok():
    assert rex.compile("a{0,65535}") is not None
    assert rex.compile("a{65535}") is not None
    assert rex.compile("a{0}") is not None


def test_literal_brace_when_not_a_quantifier():
    # "{,5}" and "{x}" are not quantifiers: "{" is a literal character
    assert rex.compile("a{,5}").search("a{,5}") is not None
    assert rex.compile("a{x}").search("a{x}") is not None


def test_duplicate_group_name():
    check("(?P<n>a)(?P<n>b)", "redefinition of group name 'n'", 9)


def test_bad_group_name():
    check("(?P<1a>x)", "bad group name", 1)
    check("(?P<>x)", "bad group name", 1)


def test_unterminated_group_name():
    check("(?P<abc", "unterminated group name", 1)


def test_unknown_group_extension():
    check("(?=x)", "unknown group extension", 1)
    check("(?!x)", "unknown group extension", 1)
    check("(?#x)", "unknown group extension", 1)


def test_bad_character_range():
    check("[z-a]", "bad character range", 4)
    check(r"[\d-z]", "bad character range", 4)


def test_invalid_hex_escape():
    check(r"\x4", "invalid hex escape", 1)
    check(r"\xZZ", "invalid hex escape", 1)
    check(r"\u12", "invalid hex escape", 1)
    check(r"\uXYZW", "invalid hex escape", 1)


def test_error_is_exception_subclass():
    assert issubclass(RegexError, Exception)
    assert issubclass(rex.RegexTimeoutError, RegexError)


def test_unknown_flag():
    with pytest.raises(RegexError, match="unknown flag"):
        rex.compile("a", flags=0x100)


def test_non_string_pattern():
    with pytest.raises(TypeError):
        rex.compile(123)
