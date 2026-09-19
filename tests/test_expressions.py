"""Expression evaluation: literals, comparison, logic, arithmetic, parens."""

import pytest

from tinytpl import Template, TplError


def render_expr(src, **ctx):
    return Template("{{ " + src + " }}").render(**ctx)


def render_cond(cond, **ctx):
    return Template("{% if " + cond + " %}T{% else %}F{% endif %}").render(**ctx)


# -- literals ---------------------------------------------------------------


def test_number_literals():
    assert render_expr("42") == "42"
    assert render_expr("3.5") == "3.5"


def test_string_literals():
    assert render_expr("'hello'") == "hello"
    assert render_expr('"world"') == "world"


def test_boolean_none_literals():
    assert render_expr("true") == "True"
    assert render_expr("false") == "False"
    assert render_expr("none") == ""


# -- arithmetic -------------------------------------------------------------


def test_arithmetic_basic():
    assert render_expr("1 + 2") == "3"
    assert render_expr("5 - 8") == "-3"
    assert render_expr("3 * 4") == "12"
    assert render_expr("7 / 2") == "3.5"
    assert render_expr("7 // 2") == "3"
    assert render_expr("7 % 2") == "1"


def test_arithmetic_precedence():
    assert render_expr("1 + 2 * 3") == "7"
    assert render_expr("10 - 2 * 3") == "4"


def test_arithmetic_parens():
    assert render_expr("(1 + 2) * 3") == "9"
    assert render_expr("((2))") == "2"


def test_unary_minus():
    assert render_expr("-5") == "-5"
    assert render_expr("-(3 + 1)") == "-4"


def test_arithmetic_with_variables():
    assert render_expr("a * 2 + b", a=3, b=1) == "7"


def test_string_concat():
    assert render_expr("'a' + 'b'") == "ab"


def test_division_by_zero_raises_tplerror():
    with pytest.raises(TplError):
        render_expr("1 / 0")


# -- comparison -------------------------------------------------------------


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("1 == 1", "T"), ("1 == 2", "F"),
        ("1 != 2", "T"), ("1 != 1", "F"),
        ("1 < 2", "T"), ("2 < 1", "F"),
        ("2 <= 2", "T"), ("3 <= 2", "F"),
        ("2 > 1", "T"), ("1 > 2", "F"),
        ("2 >= 2", "T"), ("1 >= 2", "F"),
        ("'a' == 'a'", "T"), ("'a' == 'b'", "F"),
    ],
)
def test_comparisons(expr, expected):
    assert render_cond(expr) == expected


def test_comparison_with_variables():
    assert render_cond("age >= 18", age=20) == "T"
    assert render_cond("age >= 18", age=10) == "F"


# -- logic ------------------------------------------------------------------


def test_logic_and_or_not():
    assert render_cond("true and true") == "T"
    assert render_cond("true and false") == "F"
    assert render_cond("false or true") == "T"
    assert render_cond("not true") == "F"
    assert render_cond("not false") == "T"


def test_logic_precedence():
    # and binds tighter than or
    assert render_cond("true or false and false") == "T"
    assert render_cond("(true or false) and false") == "F"


def test_logic_with_comparisons():
    assert render_cond("n > 1 and n < 10", n=5) == "T"
    assert render_cond("n < 1 or n > 10", n=5) == "F"


def test_not_with_parens():
    assert render_cond("not (a and b)", a=True, b=True) == "F"
    assert render_cond("not (a and b)", a=True, b=False) == "T"


def test_short_circuit_and():
    # missing var is falsy by default; second operand must not be evaluated
    assert render_cond("missing and missing.deep") == "F"


def test_short_circuit_or():
    assert render_cond("true or missing.deep") == "T"


# -- output expressions ------------------------------------------------------


def test_expression_in_output():
    assert render_expr("a + 1", a=2) == "3"


def test_expression_result_is_escaped():
    assert render_expr("'<' + '>'") == "&lt;&gt;"


def test_expression_with_raw():
    assert Template("{{ '<b>' | raw }}").render() == "<b>"
