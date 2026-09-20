import pytest

from storelens import astnodes as ast
from storelens.errors import StorelensError
from storelens.parser import parse, parse_one


def test_create_table():
    stmt = parse_one("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT, x REAL);")
    assert isinstance(stmt, ast.CreateTable)
    assert stmt.name == "t"
    assert stmt.columns == [("id", "INTEGER", True),
                            ("name", "TEXT", False),
                            ("x", "REAL", False)]


def test_missing_semicolon_raises():
    with pytest.raises(StorelensError) as exc:
        parse("SELECT * FROM t")
    assert "expected ';'" in str(exc.value)


def test_unknown_statement_keyword_raises():
    with pytest.raises(StorelensError) as exc:
        parse("VALUES (1);")
    assert "unknown statement keyword" in str(exc.value)
    with pytest.raises(StorelensError) as exc:
        parse("GRANT ALL ON t;")  # GRANT is not even a keyword
    assert "expected a statement" in str(exc.value)


def test_unbalanced_parentheses_raise():
    with pytest.raises(StorelensError):
        parse("SELECT (1 + 2 FROM t;")
    with pytest.raises(StorelensError):
        parse("CREATE TABLE t (a INTEGER;")


def test_expression_precedence():
    # 1 + 2 * 3 parses as 1 + (2 * 3)
    stmt = parse_one("SELECT 1 + 2 * 3 FROM t;")
    expr = stmt.items[0].expr
    assert isinstance(expr, ast.Binary) and expr.op == "+"
    assert isinstance(expr.right, ast.Binary) and expr.right.op == "*"


def test_and_or_precedence():
    # a OR b AND c parses as a OR (b AND c)
    stmt = parse_one("SELECT a OR b AND c FROM t;")
    expr = stmt.items[0].expr
    assert expr.op == "OR"
    assert expr.right.op == "AND"


def test_not_binds_tighter_than_and():
    stmt = parse_one("SELECT NOT a AND b FROM t;")
    expr = stmt.items[0].expr
    assert expr.op == "AND"
    assert isinstance(expr.left, ast.Unary) and expr.left.op == "NOT"


def test_parentheses_override_precedence():
    stmt = parse_one("SELECT (1 + 2) * 3 FROM t;")
    expr = stmt.items[0].expr
    assert expr.op == "*"
    assert expr.left.op == "+"


def test_select_full_clause_set():
    stmt = parse_one(
        "SELECT DISTINCT a AS x, COUNT(*) FROM t WHERE a > 1 "
        "GROUP BY a HAVING COUNT(*) > 2 ORDER BY x DESC, a ASC "
        "LIMIT 10 OFFSET 5;")
    assert stmt.distinct is True
    assert stmt.items[0].alias == "x"
    assert isinstance(stmt.where, ast.Binary)
    assert len(stmt.group_by) == 1
    assert isinstance(stmt.having, ast.Binary)
    assert isinstance(stmt.having.left, ast.FuncCall)
    assert stmt.order_by[0][1] == "DESC"
    assert stmt.order_by[1][1] == "ASC"
    assert stmt.limit == 10
    assert stmt.offset == 5


def test_insert_multiple_rows_and_column_list():
    stmt = parse_one("INSERT INTO t (a, b) VALUES (1, 'x'), (2, NULL);")
    assert stmt.columns == ["a", "b"]
    assert len(stmt.rows) == 2
    assert stmt.rows[1][1].value is None


def test_is_null_and_is_not_null():
    stmt = parse_one("SELECT a FROM t WHERE a IS NOT NULL;")
    assert isinstance(stmt.where, ast.IsNull)
    assert stmt.where.negated is True


def test_string_escaping_round_trip():
    stmt = parse_one("INSERT INTO t VALUES ('it''s');")
    assert stmt.rows[0][0].value == "it's"


def test_script_with_multiple_statements():
    stmts = parse("CREATE TABLE t (a INTEGER); INSERT INTO t VALUES (1); SELECT * FROM t;")
    assert len(stmts) == 3
    assert isinstance(stmts[0], ast.CreateTable)
    assert isinstance(stmts[1], ast.Insert)
    assert isinstance(stmts[2], ast.Select)


def test_limit_requires_integer():
    with pytest.raises(StorelensError):
        parse("SELECT a FROM t LIMIT 'x';")


def test_update_and_delete_parse():
    upd = parse_one("UPDATE t SET a = 1, b = 'x' WHERE a IS NULL;")
    assert len(upd.assignments) == 2
    assert isinstance(upd.where, ast.IsNull)
    dele = parse_one("DELETE FROM t WHERE a < 5;")
    assert isinstance(dele.where, ast.Binary)
