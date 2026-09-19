"""表达式求值：字面量、比较、逻辑、算术、括号。"""

import pytest

from tinytpl import Template, TplError


def render(src, **ctx):
    return Template("{{ " + src + " }}").render(**ctx)


def test_string_and_number_literals():
    assert render("'hi'") == "hi"
    assert render('"hi"') == "hi"
    assert render("42") == "42"
    assert render("2.5") == "2.5"


def test_string_escapes():
    assert render(r"'a\nb'") == "a\nb"


def test_comparisons():
    assert render("1 == 1") == "True"
    assert render("1 != 2") == "True"
    assert render("1 < 2") == "True"
    assert render("2 <= 2") == "True"
    assert render("3 > 2") == "True"
    assert render("3 >= 4") == "False"
    assert render("'a' == 'a'") == "True"


def test_chained_comparison():
    assert render("1 < 2 < 3") == "True"
    assert render("1 < 2 > 3") == "False"


def test_logic_operators():
    assert render("True and False") == "False"
    assert render("True or False") == "True"
    assert render("not True") == "False"
    assert render("not not 1") == "True"


def test_logic_short_circuit_values():
    assert render("0 or 'fallback'") == "fallback"
    assert render("'x' and 'y'") == "y"


def test_arithmetic():
    assert render("1 + 2") == "3"
    assert render("5 - 8") == "-3"
    assert render("3 * 4") == "12"
    assert render("7 / 2") == "3.5"
    assert render("7 // 2") == "3"
    assert render("7 % 3") == "1"


def test_arithmetic_precedence():
    assert render("1 + 2 * 3") == "7"
    assert render("10 - 2 * 3") == "4"


def test_parentheses():
    assert render("(1 + 2) * 3") == "9"
    assert render("not (1 == 2)") == "True"


def test_unary_minus():
    assert render("-5 + 3") == "-2"
    assert render("-(1 + 2)") == "-3"


def test_variables_in_expressions():
    assert render("a + b * 2", a=1, b=3) == "7"
    assert render("user.age >= 18", user={"age": 20}) == "True"


def test_string_concat():
    assert render("'a' + 'b'") == "ab"


def test_division_by_zero_raises():
    with pytest.raises(TplError, match="division by zero"):
        render("1 / 0")


def test_type_error_in_arithmetic_raises():
    with pytest.raises(TplError):
        render("1 + 'a'")


def test_expression_in_if():
    tpl = Template("{% if (a > 1 and b < 5) or c %}hit{% endif %}")
    assert tpl.render(a=2, b=4, c=False) == "hit"
    assert tpl.render(a=0, b=9, c=True) == "hit"
    assert tpl.render(a=0, b=9, c=False) == ""
