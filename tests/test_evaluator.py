import pytest

from sqlq.errors import SqlqError
from sqlq.evaluator import evaluate
from sqlq.parser import parse_expression as pe


def ev(sql, context=None):
    return evaluate(pe(sql), context or {})


def test_arithmetic_precedence_and_associativity():
    assert ev("2 + 3 * 4") == 14
    assert ev("(2 + 3) * 4") == 20
    assert ev("10 - 3 - 2") == 5
    assert ev("10 / 4") == 2.5
    assert ev("2 * 3 + 4 * 5") == 26


def test_unary_minus_and_plus():
    assert ev("-5") == -5
    assert ev("- -5") == 5
    assert ev("+7") == 7
    assert ev("-(2 + 3)") == -5


def test_integer_division_promotes_to_real():
    result = ev("6 / 3")
    assert result == 2.0 and isinstance(result, float)


def test_modulo_integers():
    assert ev("7 % 3") == 1
    assert ev("-7 % 3") == -1


def test_comparisons():
    assert ev("3 < 4") is True
    assert ev("3 <= 3") is True
    assert ev("3 >= 4") is False
    assert ev("3 != 4") is True
    assert ev("3 <> 3") is False
    assert ev("'abc' = 'abc'") is True
    assert ev("'a' < 'b'") is True
    assert ev("'abc' > 'ab'") is True


def test_null_propagation_in_arithmetic():
    assert ev("null + 1") is None
    assert ev("null * 1") is None


def test_null_comparisons_are_unknown():
    assert ev("null = 1") is None
    assert ev("null = null") is None
    assert ev("null != null") is None
    assert ev("null < 1") is None


def test_is_null_operators():
    assert ev("a is null", {"a": None}) is True
    assert ev("a is not null", {"a": None}) is False
    assert ev("a is not null", {"a": 1}) is True


def test_three_valued_logic_truth_table():
    assert ev("true and true") is True
    assert ev("true and false") is False
    assert ev("true and null") is None
    assert ev("false and null") is False
    assert ev("true or null") is True
    assert ev("false or null") is None
    assert ev("false or false") is False
    assert ev("not null") is None
    assert ev("not true") is False


def test_not_three_valued():
    assert ev("not (1 = null)") is None


def test_column_lookup_and_qualified_name():
    ctx = {"a": 10, "t.a": 10}
    assert ev("a * 2", ctx) == 20
    assert ev("t.a = 10", ctx) is True


def test_unknown_column_raises():
    with pytest.raises(SqlqError):
        ev("missing + 1")


def test_arithmetic_on_text_is_type_error():
    with pytest.raises(SqlqError):
        ev("'a' + 1")


def test_ordering_compare_text_with_number_is_error():
    with pytest.raises(SqlqError):
        ev("'a' < 1")


def test_equality_text_number_is_error():
    with pytest.raises(SqlqError):
        ev("'1' = 1")


def test_division_by_zero():
    with pytest.raises(SqlqError):
        ev("1 / 0")
    with pytest.raises(SqlqError):
        ev("1 % 0")


def test_logical_operator_requires_boolean():
    with pytest.raises(SqlqError):
        ev("1 AND 2")
    with pytest.raises(SqlqError):
        ev("NOT 5")


def test_numeric_cross_type_equality():
    assert ev("1 = 1.0") is True
    assert ev("1.5 < 2") is True


def test_string_literal_with_escaped_quote():
    assert ev("'it''s' = 'it''s'") is True
