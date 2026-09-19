import pytest

from sqlq.errors import SqlqError
from sqlq.evaluator import truthy, type_name
from sqlq.executor import Engine


def evaluate(sql):
    result = Engine().execute(sql)
    return result.rows[0][0]


def test_arith_precedence_and_integer_float_math():
    assert evaluate("SELECT 2 + 3 * 4;") == 14
    assert evaluate("SELECT 10 / 4;") == 2.5
    assert evaluate("SELECT 1 + 2.0;") == 3.0
    assert evaluate("SELECT -5 + 2;") == -3
    assert evaluate("SELECT 2 * -3;") == -6


def test_comparison_strings_use_dictionary_order():
    assert evaluate("SELECT 'apple' < 'banana';") is True
    assert evaluate("SELECT 'a' >= 'a';") is True
    assert evaluate("SELECT 'x' != 'y';") is True
    assert evaluate("SELECT 1 = 1.0;") is True


def test_equality_operators_aliases():
    assert evaluate("SELECT 1 == 1;") is True
    assert evaluate("SELECT 1 <> 2;") is True


def test_null_comparison_propagates_null():
    assert evaluate("SELECT NULL = 1;") is None
    assert evaluate("SELECT NULL != 'x';") is None
    assert evaluate("SELECT NULL < 1;") is None
    assert evaluate("SELECT 1 + NULL;") is None


def test_is_null_operators():
    assert evaluate("SELECT NULL IS NULL;") is True
    assert evaluate("SELECT 1 IS NULL;") is False
    assert evaluate("SELECT 1 IS NOT NULL;") is True
    assert evaluate("SELECT NULL IS NOT NULL;") is False


def test_three_valued_logic_truth_table():
    assert evaluate("SELECT (1=1) AND NULL;") is None
    assert evaluate("SELECT (1=2) AND NULL;") is False
    assert evaluate("SELECT (1=1) OR NULL;") is True
    assert evaluate("SELECT (1=2) OR NULL;") is None
    assert evaluate("SELECT NOT NULL;") is None


def test_truthy_helper():
    assert truthy(True)
    assert not truthy(False)
    assert not truthy(None)


def test_type_mismatch_arithmetic_and_compare():
    with pytest.raises(SqlqError) as info:
        evaluate("SELECT 'a' + 1;")
    assert "numeric" in str(info.value)
    with pytest.raises(SqlqError):
        evaluate("SELECT 'a' > 1;")


def test_division_by_zero():
    with pytest.raises(SqlqError):
        evaluate("SELECT 1 / 0;")


def test_parenthesized_boolean_expression():
    assert evaluate("SELECT (1 < 2 OR 5 < 0) AND NOT (2 > 3);") is True


def test_type_name_helper():
    assert type_name(None) == "NULL"
    assert type_name(1) == "INTEGER"
    assert type_name(1.0) == "REAL"
    assert type_name("s") == "TEXT"
