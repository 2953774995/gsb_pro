import pytest

from sqlq import ast_nodes as ast
from sqlq.errors import SqlqError
from sqlq.parser import parse_script, parse_statement


def test_missing_semicolon_is_error():
    with pytest.raises(SqlqError) as info:
        parse_statement("SELECT 1")
    assert "';'" in str(info.value)


def test_unknown_leading_keyword():
    with pytest.raises(SqlqError):
        parse_statement("FOO BAR;")


def test_unmatched_parenthesis_expression():
    with pytest.raises(SqlqError):
        parse_statement("SELECT (1 + 2 FROM t;")


def test_unmatched_parenthesis_create_table():
    with pytest.raises(SqlqError):
        parse_statement("CREATE TABLE t (a INTEGER;")


def test_chained_comparison_rejected():
    with pytest.raises(SqlqError):
        parse_statement("SELECT * FROM t WHERE a = b = c;")


def test_expression_precedence_and_associativity():
    node = parse_statement("SELECT 1 + 2 * 3 - 4 / 2;").items[0].expr
    # (1 + (2*3)) - (4/2)
    assert node.op == "-"
    assert node.left.op == "+"
    assert node.left.right.op == "*"
    assert node.right.op == "/"


def test_not_binds_tighter_than_and_or():
    node = parse_statement(
        "SELECT * FROM t WHERE NOT a AND b OR c;").where
    assert node.op == "OR"
    assert node.left.op == "AND"
    assert isinstance(node.left.left, ast.UnaryOp)
    assert node.left.left.op == "NOT"


def test_parentheses_group_override():
    node = parse_statement("SELECT (1 + 2) * 3;").items[0].expr
    assert node.op == "*"
    assert node.left.op == "+"


def test_is_null_and_is_not_null():
    where = parse_statement("SELECT * FROM t WHERE a IS NOT NULL;").where
    assert isinstance(where, ast.IsNull) and where.negated is True
    where2 = parse_statement("SELECT * FROM t WHERE a IS NULL;").where
    assert isinstance(where2, ast.IsNull) and where2.negated is False


def test_parse_create_table_with_primary_key_and_types():
    node = parse_statement(
        "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT, ratio REAL);")
    assert node.primary_key == "id"
    assert node.columns == [("id", "INTEGER"), ("name", "TEXT"),
                            ("ratio", "REAL")]


def test_int_alias_type_normalised():
    node = parse_statement("CREATE TABLE t (n INT);")
    assert node.columns[0][1] == "INTEGER"


def test_duplicate_column_in_create_table():
    with pytest.raises(SqlqError):
        parse_statement("CREATE TABLE t (a INTEGER, A TEXT);")


def test_insert_with_partial_column_list():
    node = parse_statement("INSERT INTO t (a, b) VALUES (1, 'x');")
    assert node.columns == ["a", "b"]
    assert len(node.values) == 2


def test_parse_select_clauses():
    node = parse_statement(
        "SELECT DISTINCT a AS x FROM t WHERE a > 0 GROUP BY a "
        "HAVING COUNT(*) > 1 ORDER BY x DESC LIMIT 5 OFFSET 2;")
    assert node.distinct is True
    assert node.table == "t"
    assert node.items[0].alias == "x"
    assert isinstance(node.having, ast.BinaryOp)
    assert node.order_by[0].descending is True
    assert node.limit == 5 and node.offset == 2


def test_limit_comma_offset_form():
    node = parse_statement("SELECT * FROM t LIMIT 3, 5;")
    assert node.offset == 3 and node.limit == 5


def test_limit_requires_integer():
    with pytest.raises(SqlqError):
        parse_statement("SELECT * FROM t LIMIT 1.5;")


def test_negative_limit_rejected():
    with pytest.raises(SqlqError):
        parse_statement("SELECT * FROM t LIMIT -1;")


def test_unknown_function_rejected():
    with pytest.raises(SqlqError):
        parse_statement("SELECT foo(a) FROM t;")


def test_count_star_only_allowed_for_count():
    with pytest.raises(SqlqError):
        parse_statement("SELECT SUM(*) FROM t;")


def test_order_by_asc_desc():
    node = parse_statement(
        "SELECT * FROM t ORDER BY a ASC, b DESC;")
    assert node.order_by[0].descending is False
    assert node.order_by[1].descending is True


def test_parse_multiple_statements_requires_all_terminated():
    nodes = parse_script("SELECT 1; SELECT 2;")
    assert len(nodes) == 2
    with pytest.raises(SqlqError):
        parse_script("SELECT 1; SELECT 2")


def test_empty_script_error():
    with pytest.raises(SqlqError):
        parse_script("   -- only a comment\n")
