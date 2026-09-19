"""Invalid patterns must raise RegexError with reason and column."""

import pytest

import rex
from rex.errors import RegexError, RegexTimeoutError


def test_error_is_value_error_compatible():
    assert issubclass(RegexError, Exception)
    assert issubclass(RegexTimeoutError, RegexError)


def test_error_carries_position_and_column():
    with pytest.raises(RegexError) as exc:
        rex.compile("a*(")
    assert exc.value.pos == 2
    assert "column 3" in str(exc.value)


@pytest.mark.parametrize(
    "pattern,pos",
    [
        ("(", 0),
        ("(a", 0),
        ("a)", 1),
        ("((a)", 0),
        ("[a", 0),
        ("*", 0),
        ("+a", 0),
        ("?", 0),
        ("a**", 2),
        ("a{2}*", 4),
        ("a{3,2}", 1),
        ("a{70000}", 1),
        ("a{1,70000}", 1),
        (r"\q", 0),
        (r"abc\1", 3),
        (r"\x4", 0),
        (r"\u12", 0),
        ("(?P<n>a)(?P<n>b)", 12),
        ("(?P<bad!>a)", 4),
        ("[z-a]", 2),
        ("abc\\", 3),
    ],
)
def test_invalid_patterns(pattern, pos):
    with pytest.raises(RegexError) as exc:
        rex.compile(pattern)
    assert exc.value.pos == pos, (pattern, exc.value.pos)


def test_error_message_is_descriptive():
    with pytest.raises(RegexError) as exc:
        rex.compile("abc{2,1}")
    message = str(exc.value)
    assert "repeat" in message
    assert "column" in message


def test_brace_overflow_message():
    with pytest.raises(RegexError) as exc:
        rex.compile("x{65536}")
    assert "65535" in str(exc.value)


def test_unsupported_backreference_is_explicit():
    with pytest.raises(RegexError) as exc:
        rex.compile(r"(a)\1")
    message = str(exc.value).lower()
    assert "backreference" in message or "not implemented" in message


def test_unknown_flag_value():
    with pytest.raises(ValueError):
        rex.compile("a", flags=1 << 20)


def test_timeout_is_a_regex_error():
    p = rex.compile(r"(a+)+$", max_steps=1000)
    with pytest.raises(RegexError):
        p.fullmatch("a" * 20 + "b")
