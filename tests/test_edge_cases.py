"""Extra boundary semantics discovered during implementation."""

import pytest

from sqlq import Engine, SqlqError


def test_qualified_column_names():
    engine = Engine()
    engine.execute("CREATE TABLE t (a INTEGER PRIMARY KEY, b TEXT);")
    engine.execute("INSERT INTO t VALUES (1, 'x');")
    result = engine.execute(
        "SELECT t.a, t.b FROM t WHERE t.a = 1 AND t.b IS NOT NULL;")
    assert result.rows == [(1, "x")]


def test_qualified_column_with_unknown_table():
    engine = Engine()
    engine.execute("CREATE TABLE t (a INTEGER);")
    with pytest.raises(SqlqError):
        engine.execute("SELECT other.a FROM t;")


def test_qualified_update_assignment():
    engine = Engine()
    engine.execute("CREATE TABLE u (a INTEGER PRIMARY KEY, b INTEGER);")
    engine.execute("INSERT INTO u VALUES (1, 10);")
    engine.execute("UPDATE u SET u.b = 20 WHERE u.a = 1;")
    assert engine.execute("SELECT b FROM u;").rows == [(20,)]


def test_qualified_update_wrong_table_name():
    engine = Engine()
    engine.execute("CREATE TABLE u (a INTEGER);")
    engine.execute("INSERT INTO u VALUES (1);")
    with pytest.raises(SqlqError):
        engine.execute("UPDATE u SET v.a = 2;")


def test_null_group_is_single_group_and_count_ignores_null():
    engine = Engine()
    engine.execute("CREATE TABLE t (g TEXT, v INTEGER);")
    rows = [("a", 1), ("a", 2), (None, 3), (None, None), ("b", None)]
    for group, value in rows:
        group_sql = "NULL" if group is None else "'{}'".format(group)
        value_sql = "NULL" if value is None else str(value)
        engine.execute(
            "INSERT INTO t VALUES ({}, {});".format(group_sql, value_sql))
    result = engine.execute(
        "SELECT g, COUNT(*), COUNT(v), SUM(v) FROM t GROUP BY g "
        "ORDER BY g;")
    # NULL group sorts first under ASC.
    assert result.rows == [
        (None, 2, 1, 3),
        ("a", 2, 2, 3),
        ("b", 1, 0, None),
    ]


def test_empty_table_aggregate_values():
    engine = Engine()
    engine.execute("CREATE TABLE t (a INTEGER, b TEXT);")
    result = engine.execute(
        "SELECT COUNT(*), COUNT(a), SUM(a), AVG(a), MIN(a), MAX(a) FROM t;")
    assert result.rows == [(0, 0, None, None, None, None)]


def test_empty_where_then_limit_on_empty_table():
    engine = Engine()
    engine.execute("CREATE TABLE t (a INTEGER);")
    result = engine.execute("SELECT * FROM t WHERE a > 0 LIMIT 5 OFFSET 3;")
    assert result.columns == ["a"]
    assert result.rows == []


def test_offset_alone_allowed():
    engine = Engine()
    engine.execute("CREATE TABLE t (a INTEGER);")
    for index in range(5):
        engine.execute("INSERT INTO t VALUES ({});".format(index))
    result = engine.execute(
        "SELECT a FROM t ORDER BY a OFFSET 2;")
    assert result.rows == [(2,), (3,), (4,)]


def test_integer_sum_preserves_integer_type():
    engine = Engine()
    engine.execute("CREATE TABLE t (a INTEGER);")
    engine.execute_script(
        "INSERT INTO t VALUES (1); INSERT INTO t VALUES (2);")
    row = engine.execute("SELECT SUM(a), AVG(a) FROM t;").rows[0]
    assert row == (3, 1.5)
    assert type(row[0]) is int


def test_distinct_star_deduplicates_full_rows():
    engine = Engine()
    engine.execute("CREATE TABLE t (a INTEGER, b INTEGER);")
    engine.execute_script(
        "INSERT INTO t VALUES (1, 2); INSERT INTO t VALUES (1, 2);"
        "INSERT INTO t VALUES (1, 3);")
    assert engine.execute("SELECT DISTINCT * FROM t ORDER BY a, b;").rows \
        == [(1, 2), (1, 3)]


def test_star_with_grouping_rejected():
    engine = Engine()
    engine.execute("CREATE TABLE t (a INTEGER, b INTEGER);")
    with pytest.raises(SqlqError):
        engine.execute("SELECT *, COUNT(*) FROM t GROUP BY a;")


def test_group_by_alias_name():
    engine = Engine()
    engine.execute("CREATE TABLE t (a INTEGER, b INTEGER);")
    engine.execute_script(
        "INSERT INTO t VALUES (1, 10); INSERT INTO t VALUES (1, 20);")
    result = engine.execute(
        "SELECT a AS x, SUM(b) FROM t GROUP BY x ORDER BY x;")
    assert result.rows == [(1, 30)]


def test_group_by_expression_matching_projection():
    engine = Engine()
    engine.execute("CREATE TABLE t (a INTEGER);")
    engine.execute_script(
        "INSERT INTO t VALUES (1); INSERT INTO t VALUES (9);"
        "INSERT INTO t VALUES (12);")
    result = engine.execute(
        "SELECT a > 5 AS big, COUNT(*) FROM t GROUP BY a > 5 ORDER BY big;")
    assert result.rows == [(False, 1), (True, 2)]


def test_having_without_aggregation_is_error():
    engine = Engine()
    engine.execute("CREATE TABLE t (a INTEGER);")
    with pytest.raises(SqlqError):
        engine.execute("SELECT a FROM t HAVING a > 1;")


def test_insert_columns_reject_expressions_with_columns():
    engine = Engine()
    engine.execute("CREATE TABLE t (a INTEGER);")
    with pytest.raises(SqlqError):
        engine.execute("INSERT INTO t VALUES (a + 1);")


def test_float_into_integer_column_rejected():
    engine = Engine()
    engine.execute("CREATE TABLE t (a INTEGER);")
    with pytest.raises(SqlqError):
        engine.execute("INSERT INTO t VALUES (1.5);")


def test_select_constant_arithmetic_and_strings():
    result = Engine().execute(
        "SELECT 'it''s' AS s, 2 * (3 + 4) AS n, 3.14 < 4, NULL IS NULL;")
    assert result.rows == [("it's", 14, True, True)]
