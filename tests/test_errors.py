"""Invalid patterns must raise RegexError with reason and column."""

import pytest

import rex


def _assert_error(pattern, column, *fragments):
    with pytest.raises(rex.RegexError) as excinfo:
        rex.compile(pattern)
    message = str(excinfo.value)
    assert "column %d" % column in message, message
    for fragment in fragments:
        assert fragment in message, message


def test_unterminated_group():
    _assert_error("(abc", 1, "unterminated group")
    _assert_error("a(b", 2, "unterminated group")
    _assert_error("(?:abc", 1, "unterminated group")


def test_unbalanced_close_paren():
    _assert_error(")", 1, "unbalanced")
    _assert_error("ab)c", 3, "unbalanced")


def test_unterminated_class():
    _assert_error("[abc", 1, "unterminated character class")
    _assert_error("x[abc", 2, "unterminated character class")


def test_empty_class():
    with pytest.raises(rex.RegexError):
        rex.compile("[]")


def test_quantifier_without_target():
    _assert_error("*abc", 1, "nothing to repeat")
    _assert_error("+abc", 1, "nothing to repeat")
    _assert_error("?abc", 1, "nothing to repeat")
    _assert_error("{2}abc", 1, "nothing to repeat")


def test_quantifier_after_anchor():
    _assert_error("^*", 2, "nothing to repeat")
    _assert_error("a$+", 3, "nothing to repeat")


def test_unknown_escape():
    _assert_error(r"\q", 1, "unknown escape")
    _assert_error(r"ab\q", 3, "unknown escape")


def test_bad_hex_escape():
    _assert_error(r"\x4", 1, "hex")
    _assert_error(r"\xzz", 1, "hex")
    _assert_error(r"\u12", 1, "hex")


def test_brace_bounds():
    _assert_error("a{3,2}", 2, "out of order")
    _assert_error("a{65536}", 2, "out of range")
    _assert_error("a{1,65536}", 2, "out of range")


def test_duplicate_group_name():
    _assert_error("(?P<n>a)(?P<n>b)", 13, "duplicate")


def test_backreference_not_supported():
    _assert_error(r"(a)\1", 4, "not supported")


def test_trailing_backslash():
    _assert_error("ab\\", 3, "trailing backslash")


def test_timeout_error_is_regex_error():
    assert issubclass(rex.RegexTimeoutError, rex.RegexError)


def test_error_attributes():
    try:
        rex.compile("(abc")
    except rex.RegexError as exc:
        assert exc.pos == 0
        assert "unterminated" in exc.message
    else:
        raise AssertionError("expected RegexError")
