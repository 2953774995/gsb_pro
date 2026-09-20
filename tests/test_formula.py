from sheet.formula import Evaluator, parse_formula, describe_ast
from sheet.model import CellAddress, CellError, display_value


def evaluate(text, cells=None):
    values = {CellAddress(col, row): value for (col, row), value in (cells or {}).items()}
    return Evaluator(lambda addr: values.get(addr)).eval(parse_formula(text))


def test_arithmetic_precedence_and_parentheses():
    assert evaluate("=1+2*3") == 7
    assert evaluate("=(1+2)*3") == 9
    assert evaluate("=10-2-3") == 5
    assert evaluate("=2*3/4") == 1.5


def test_unary_negative_numbers():
    assert evaluate("=-5") == -5
    assert evaluate("=3+-2") == 1
    assert evaluate("=--4") == 4


def test_cell_reference_formula():
    assert evaluate("=A1+B2*2", {(1, 1): 10, (2, 2): 3}) == 16


def test_function_nesting_with_ranges():
    cells = {
        (1, 1): 1, (1, 2): 2, (1, 3): None, (1, 4): 7, (1, 5): 0,
        (2, 1): 4, (2, 2): 9, (2, 3): 2, (2, 4): None, (2, 5): 6,
    }
    assert evaluate("=SUM(A1:A5)+MAX(B1:B5)", cells) == 19
    assert evaluate("=AVG(A1:A5)", cells) == 2.5
    assert evaluate("=MIN(B1:B5)", cells) == 2
    assert evaluate("=COUNT(A1:B5)", cells) == 8


def test_comparison_returns_booleans():
    assert display_value(evaluate("=A1>100", {(1, 1): 101})) == "TRUE"
    assert display_value(evaluate("=A1>100", {(1, 1): 50})) == "FALSE"
    assert display_value(evaluate("=A1=B1", {(1, 1): 2, (2, 1): 2})) == "TRUE"


def test_string_concatenation():
    assert evaluate('="合计: "&B2', {(2, 2): "8"}) == "合计: 8"


def test_division_by_zero_error():
    value = evaluate("=1/0")
    assert isinstance(value, CellError)
    assert display_value(value) == "#DIV/0!"


def test_parser_ast_describes_nested_calls():
    tree = parse_formula("=SUM(A1:A5)+MAX(B1:B5)")
    assert describe_ast(tree) == "(SUM(A1:A5) + MAX(B1:B5))"


def test_concatenation_converts_numbers_and_booleans():
    assert evaluate('="合计: "&B2', {(2, 2): 8}) == "合计: 8"
    assert evaluate("=A1&TRUE", {(1, 1): 1}) == "1TRUE"


def test_errors_propagate_through_functions():
    assert display_value(evaluate("=SUM(1/0,2)")) == "#DIV/0!"
