import pytest

from storelens.parser import parse, parse_script
from storelens import ast_nodes as ast
from storelens.errors import StorelensError


def test_missing_semicolon_raises():
    with pytest.raises(StorelensError, match="expected ';'"):
        parse("SELECT a FROM t")


def test_unknown_statement_keyword():
    with pytest.raises(StorelensError, match="unknown statement keyword"):
        parse("TRUNCATE t;")


def test_unexpected_token_start():
    with pytest.raises(StorelensError, match="expected a statement"):
        parse("42;")


def test_unbalanced_parenthesis():
    with pytest.raises(StorelensError, match="expected '\\)'"):
        parse("SELECT (a + 1 FROM t;")


def test_create_table_ast():
    stmt = parse("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT, v REAL);")
    assert isinstance(stmt, ast.CreateTable)
    assert stmt.name == "t"
    assert [(c.name, c.type_name, c.primary_key) for c in stmt.columns] == [
        ("id", "INTEGER", True), ("name", "TEXT", False),
        ("v", "REAL", False)]


def test_double_primary_key_rejected():
    with pytest.raises(StorelensError, match="only one PRIMARY KEY"):
        parse("CREATE TABLE t (a INTEGER PRIMARY KEY, b INTEGER PRIMARY KEY);")


def test_bad_column_type():
    with pytest.raises(StorelensError, match="expected column type"):
        parse("CREATE TABLE t (a BLOB);")


def test_select_precedence_and_or():
    stmt = parse("SELECT a FROM t WHERE a = 1 OR b = 2 AND c = 3;")
    where = stmt.where
    # AND binds tighter: OR at the top
    assert where.op == "OR"
    assert where.right.op == "AND"


def test_arithmetic_precedence():
    stmt = parse("SELECT 1 + 2 * 3 FROM t;")
    expr = stmt.items[0].expr
    assert expr.op == "+"
    assert expr.right.op == "*"


def test_parentheses_override_precedence():
    stmt = parse("SELECT (1 + 2) * 3 FROM t;")
    expr = stmt.items[0].expr
    assert expr.op == "*"
    assert expr.left.op == "+"


def test_not_binds_tighter_than_and():
    stmt = parse("SELECT a FROM t WHERE NOT a = 1 AND b = 2;")
    assert stmt.where.op == "AND"
    assert isinstance(stmt.where.left, ast.UnaryOp)


def test_is_null_and_is_not_null():
    stmt = parse("SELECT a FROM t WHERE a IS NULL OR b IS NOT NULL;")
    assert isinstance(stmt.where.left, ast.IsNull)
    assert stmt.where.left.negated is False
    assert stmt.where.right.negated is True


def test_alias_with_and_without_as():
    stmt = parse("SELECT a AS x, b y FROM t;")
    assert stmt.items[0].alias == "x"
    assert stmt.items[1].alias == "y"


def test_limit_offset_parsing():
    stmt = parse("SELECT a FROM t ORDER BY a DESC LIMIT 10 OFFSET 5;")
    assert stmt.limit == 10
    assert stmt.offset == 5
    assert stmt.order_by[0].descending is True


def test_limit_requires_non_negative_integer():
    with pytest.raises(StorelensError, match="LIMIT requires"):
        parse("SELECT a FROM t LIMIT -1;")
    with pytest.raises(StorelensError, match="LIMIT requires"):
        parse("SELECT a FROM t LIMIT 1.5;")


def test_count_star():
    stmt = parse("SELECT COUNT(*) FROM t;")
    assert isinstance(stmt.items[0].expr, ast.FuncCall)
    assert stmt.items[0].expr.star is True


def test_script_multiple_statements():
    stmts = parse_script("CREATE TABLE t (a INTEGER); INSERT INTO t VALUES (1); SELECT * FROM t;")
    assert len(stmts) == 3
    assert isinstance(stmts[0], ast.CreateTable)
    assert isinstance(stmts[1], ast.Insert)
    assert isinstance(stmts[2], ast.Select)


def test_insert_multiple_rows():
    stmt = parse("INSERT INTO t (a, b) VALUES (1, 'x'), (2, 'y');")
    assert stmt.columns == ["a", "b"]
    assert len(stmt.rows) == 2


def test_update_and_delete_ast():
    upd = parse("UPDATE t SET a = 1, b = b + 1 WHERE a > 0;")
    assert [c for c, _ in upd.assignments] == ["a", "b"]
    assert upd.where is not None
    dele = parse("DELETE FROM t;")
    assert dele.where is None
