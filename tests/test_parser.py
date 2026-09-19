import pytest

from sqlq import ast_nodes as ast
from sqlq.errors import SqlqSyntaxError
from sqlq.parser import parse, parse_expression, parse_script


def test_parse_create_table_ast():
    stmt = parse("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT, x REAL);")
    assert isinstance(stmt, ast.CreateTable)
    assert stmt.table == "t"
    assert [(c.name, c.data_type, c.primary_key) for c in stmt.columns] == [
        ("id", "INTEGER", True),
        ("name", "TEXT", False),
        ("x", "REAL", False),
    ]


def test_missing_semicolon_is_syntax_error():
    with pytest.raises(SqlqSyntaxError) as info:
        parse("SELECT 1")
    assert "';'" in str(info.value)


def test_unknown_statement():
    with pytest.raises(SqlqSyntaxError):
        parse("RANDOM MAGIC 1;")


def test_unbalanced_parentheses():
    with pytest.raises(SqlqSyntaxError):
        parse("SELECT (1 + 2;")
    with pytest.raises(SqlqSyntaxError):
        parse("SELECT 1 + 2);")


def test_expression_precedence():
    expr = parse_expression("1 + 2 * 3 - 4 / 2")
    # (1 + (2*3)) - (4/2)
    assert expr.op == "-"
    assert expr.left.op == "+"
    assert expr.left.right.op == "*"
    assert expr.right.op == "/"


def test_parenthesized_expression():
    expr = parse_expression("(1 + 2) * 3")
    assert expr.op == "*"
    assert expr.left.op == "+"


def test_comparison_below_arithmetic():
    expr = parse_expression("a + 1 > b - 2")
    assert expr.op == ">"
    assert expr.left.op == "+"
    assert expr.right.op == "-"


def test_not_and_or_precedence():
    expr = parse_expression("NOT a AND b OR c")
    # (NOT a AND b) OR c
    assert expr.op == "OR"
    assert expr.left.op == "AND"
    assert isinstance(expr.left.left, ast.UnaryOp)
    assert expr.left.left.op == "NOT"


def test_is_null_and_is_not_null():
    expr = parse_expression("a IS NOT NULL")
    assert isinstance(expr, ast.IsNull) and expr.negated
    expr = parse_expression("a IS NULL")
    assert isinstance(expr, ast.IsNull) and not expr.negated


def test_aggregate_star_parsing():
    stmt = parse("SELECT COUNT(*), SUM(DISTINCT x), AVG(x) FROM t;")
    calls = [item.expr for item in stmt.items]
    assert calls[0].star and calls[0].name == "COUNT"
    assert calls[1].distinct and calls[1].name == "SUM"
    assert calls[2].name == "AVG"


def test_count_star_only():
    with pytest.raises(SqlqSyntaxError):
        parse("SELECT SUM(*) FROM t;")


def test_unknown_function():
    with pytest.raises(SqlqSyntaxError):
        parse("SELECT foobar(x) FROM t;")


def test_select_aliases():
    stmt = parse("SELECT x AS a, y b, z FROM t;")
    assert [item.alias for item in stmt.items] == ["a", "b", None]


def test_star_and_qualified_star():
    stmt = parse("SELECT *, t.x FROM t;")
    assert isinstance(stmt.items[0], ast.Star)
    stmt2 = parse("SELECT t.* FROM t;")
    assert isinstance(stmt2.items[0], ast.QualifiedStar)


def test_order_by_asc_desc_and_limit_offset():
    stmt = parse("SELECT x FROM t ORDER BY a ASC, b DESC LIMIT 5 OFFSET 2;")
    assert stmt.order_by[0].descending is False
    assert stmt.order_by[1].descending is True
    assert stmt.limit.value == 5
    assert stmt.offset.value == 2


def test_offset_without_limit():
    with pytest.raises(SqlqSyntaxError):
        parse("SELECT x FROM t OFFSET 2;")


def test_insert_update_delete_shapes():
    insert = parse("INSERT INTO t (a, b) VALUES (1, 'x');")
    assert insert.columns == ["a", "b"]
    update = parse("UPDATE t SET a = 2, b = 'y' WHERE a = 1;")
    assert len(update.assignments) == 2 and update.where is not None
    delete = parse("DELETE FROM t WHERE a = 1;")
    assert delete.where is not None


def test_invalid_column_type():
    with pytest.raises(SqlqSyntaxError):
        parse("CREATE TABLE t (a BLOB);")


def test_duplicate_column_in_ddl():
    with pytest.raises(SqlqSyntaxError):
        parse("CREATE TABLE t (a INTEGER, a TEXT);")


def test_parse_script_multiple_statements():
    stmts = parse_script("SELECT 1; SELECT 2;")
    assert len(stmts) == 2


def test_empty_script():
    assert parse_script("-- just a comment\n") == []


def test_trailing_garbage_after_expression():
    with pytest.raises(SqlqSyntaxError):
        parse("SELECT 1 1;")


def test_unsupported_join_is_rejected():
    with pytest.raises(SqlqSyntaxError):
        parse("SELECT * FROM a JOIN b ON a.id = b.id;")
