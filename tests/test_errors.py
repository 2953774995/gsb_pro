"""非法模式错误测试：错误类型、原因描述与列号断言。"""

import pytest

from datamask import PatternError, compile
from datamask.parser import parse


def expect_error(pattern, column, msg_part):
    with pytest.raises(PatternError) as excinfo:
        parse(pattern)
    err = excinfo.value
    assert err.column == column, "pattern=%r, err=%r" % (pattern, err)
    assert msg_part in err.message
    # 字符串形式同时包含原因与列号
    assert "column %d" % column in str(err)
    return err


def test_unterminated_group():
    expect_error("abc(", 3, "unterminated group")
    expect_error("(a(b)", 0, "unterminated group")


def test_unbalanced_close_paren():
    expect_error("a)", 1, "unbalanced parenthesis")
    expect_error(")", 0, "unbalanced parenthesis")


def test_unterminated_class():
    expect_error("[abc", 0, "unterminated character class")
    expect_error("xy[", 2, "unterminated character class")


def test_empty_class():
    # [] 中 ] 作为首字符是字面量，随后类未闭合
    expect_error("[]", 0, "unterminated character class")


def test_bad_range_out_of_order():
    expect_error("[z-a]", 3, "out of order")


def test_class_code_in_range():
    expect_error(r"[a-\d]", 3, "class code not allowed in range")


def test_quantifier_without_atom():
    expect_error("*abc", 0, "nothing to repeat")
    expect_error("+abc", 0, "nothing to repeat")
    expect_error("?abc", 0, "nothing to repeat")
    expect_error("a|*", 2, "nothing to repeat")
    expect_error("{2}a", 0, "nothing to repeat")


def test_anchor_not_repeatable():
    expect_error("^*", 1, "anchor is not repeatable")
    expect_error("$+", 1, "anchor is not repeatable")


def test_multiple_repeat():
    expect_error("a**", 2, "multiple repeat")
    expect_error("a*{2}", 2, "multiple repeat")
    expect_error("a??+", 3, "multiple repeat")


def test_repeat_min_greater_than_max():
    expect_error("a{3,2}", 1, "greater than max")


def test_repeat_out_of_range():
    expect_error("a{1,65536}", 1, "out of range")
    expect_error("a{65536}", 1, "out of range")
    # 边界：65535 合法
    parse("a{65535}")


def test_unknown_escape():
    expect_error(r"a\q", 1, r"unknown escape '\q'")
    expect_error(r"\A", 0, "unknown escape")


def test_trailing_backslash():
    expect_error("ab\\", 2, "trailing backslash")


def test_invalid_hex_escape():
    expect_error(r"\x4", 0, "invalid hex escape")
    expect_error(r"\xZZ", 0, "invalid hex escape")
    expect_error(r"\u12", 0, "invalid hex escape")
    expect_error(r"\uZZZZ", 0, "invalid hex escape")


def test_backreference_not_supported():
    err = expect_error(r"(a)\1", 3, "not supported")
    assert "backreference" in err.message


def test_duplicate_group_name():
    expect_error("(?P<x>a)(?P<x>b)", 8, "duplicate group name")


def test_bad_group_name():
    expect_error("(?P<1x>a)", 0, "bad character in group name")


def test_unknown_group_extension():
    expect_error("(?=a)", 0, "unknown group extension")
    expect_error("(?P=a)", 0, "unknown group extension")


def test_error_carries_pattern():
    with pytest.raises(PatternError) as excinfo:
        parse("a\\q")
    assert excinfo.value.pattern == "a\\q"


def test_compile_also_raises():
    with pytest.raises(PatternError):
        compile("(unclosed")
