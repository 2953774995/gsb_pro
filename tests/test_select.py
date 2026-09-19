import pytest

from sqlq.errors import SqlqError
from sqlq.executor import Engine


def sales_engine():
    engine = Engine()
    engine.execute(
        "CREATE TABLE sales (id INTEGER PRIMARY KEY, region TEXT, "
        "amount INTEGER, qty REAL);")
    rows = [
        (1, "east", 10, 1.0),
        (2, "east", 20, 2.0),
        (3, "west", None, 3.0),
        (4, "west", 30, None),
        (5, "east", None, 5.0),
        (6, "north", 0, 0.0),
    ]
    for row_id, region, amount, qty in rows:
        amount_sql = "NULL" if amount is None else str(amount)
        qty_sql = "NULL" if qty is None else str(qty)
        engine.execute(
            "INSERT INTO sales VALUES ({}, '{}', {}, {});".format(
                row_id, region, amount_sql, qty_sql))
    return engine


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

def test_star_projection_header_and_order():
    engine = sales_engine()
    result = engine.execute("SELECT * FROM sales WHERE id = 1;")
    assert result.columns == ["id", "region", "amount", "qty"]
    assert result.rows == [(1, "east", 10, 1.0)]


def test_projection_alias_and_expression():
    engine = sales_engine()
    result = engine.execute(
        "SELECT amount * 2 AS doubled, id FROM sales WHERE id = 1;")
    assert result.columns == ["doubled", "id"]
    assert result.rows == [(20, 1)]


def test_unknown_column_reference():
    engine = sales_engine()
    with pytest.raises(SqlqError):
        engine.execute("SELECT nope FROM sales;")
    with pytest.raises(SqlqError):
        engine.execute("SELECT * FROM sales WHERE nope = 1;")
    with pytest.raises(SqlqError):
        engine.execute("SELECT * FROM sales ORDER BY nope;")


def test_unknown_table():
    with pytest.raises(SqlqError):
        Engine().execute("SELECT * FROM nowhere;")


# ---------------------------------------------------------------------------
# WHERE
# ---------------------------------------------------------------------------

def test_where_comparison_logical_not_and_parens():
    engine = sales_engine()
    result = engine.execute(
        "SELECT id FROM sales WHERE NOT (region = 'east') AND id > 3;")
    assert result.rows == [(4,), (6,)]


def test_where_null_never_matches():
    engine = sales_engine()
    assert engine.execute(
        "SELECT id FROM sales WHERE amount = NULL;").rows == []
    assert engine.execute(
        "SELECT id FROM sales WHERE amount != NULL;").rows == []


def test_where_is_null_and_is_not_null():
    engine = sales_engine()
    ids_null = engine.execute(
        "SELECT id FROM sales WHERE amount IS NULL ORDER BY id;").rows
    ids_not_null = engine.execute(
        "SELECT id FROM sales WHERE amount IS NOT NULL ORDER BY id;").rows
    assert ids_null == [(3,), (5,)]
    assert ids_not_null == [(1,), (2,), (4,), (6,)]


def test_string_comparison_dictionary_order_in_where():
    engine = sales_engine()
    result = engine.execute(
        "SELECT id FROM sales WHERE region < 'north' ORDER BY id;")
    assert result.rows == [(1,), (2,), (5,)]


# ---------------------------------------------------------------------------
# Aggregates / GROUP BY / HAVING
# ---------------------------------------------------------------------------

def test_aggregate_on_empty_table_returns_single_null_row():
    engine = Engine()
    engine.execute("CREATE TABLE t (a INTEGER, b TEXT);")
    result = engine.execute(
        "SELECT COUNT(*), COUNT(a), SUM(a), AVG(a), MIN(a), MAX(a) FROM t;")
    assert result.rows == [(0, 0, None, None, None, None)]


def test_aggregates_ignore_nulls():
    engine = sales_engine()
    result = engine.execute(
        "SELECT COUNT(*), COUNT(amount), SUM(amount), AVG(amount), "
        "MIN(amount), MAX(amount) FROM sales;")
    assert result.rows == [(6, 4, 60, 15.0, 0, 30)]


def test_sum_of_real_division():
    engine = sales_engine()
    result = engine.execute("SELECT SUM(qty), AVG(qty) FROM sales;")
    assert result.rows == [(11.0, 11.0 / 5)]


def test_sum_text_column_is_type_error():
    engine = sales_engine()
    with pytest.raises(SqlqError) as info:
        engine.execute("SELECT SUM(region) FROM sales;")
    assert "TEXT" in str(info.value)
    with pytest.raises(SqlqError):
        engine.execute("SELECT AVG(region) FROM sales;")


def test_min_max_on_text_use_dictionary_order():
    engine = sales_engine()
    result = engine.execute(
        "SELECT MIN(region), MAX(region) FROM sales;")
    assert result.rows == [("east", "west")]


def test_group_by_basic_groups_and_null_group():
    engine = sales_engine()
    result = engine.execute(
        "SELECT amount, COUNT(*) FROM sales GROUP BY amount ORDER BY amount;")
    # NULLs form their own group and sort first under ASC.
    assert result.rows == [(None, 2), (0, 1), (10, 1), (20, 1), (30, 1)]


def test_group_by_with_having():
    engine = sales_engine()
    result = engine.execute(
        "SELECT region, COUNT(*) AS n FROM sales GROUP BY region "
        "HAVING COUNT(*) >= 2 ORDER BY region;")
    assert result.rows == [("east", 3), ("west", 2)]


def test_group_by_having_references_aggregate_expression():
    engine = sales_engine()
    result = engine.execute(
        "SELECT region FROM sales GROUP BY region HAVING SUM(amount) > 5;")
    assert result.rows == [("east",), ("west",)]


def test_ungrouped_column_with_aggregate_is_error():
    engine = sales_engine()
    with pytest.raises(SqlqError):
        engine.execute("SELECT region, COUNT(*) FROM sales;")


def test_non_grouped_column_in_having_is_error():
    engine = sales_engine()
    with pytest.raises(SqlqError):
        engine.execute(
            "SELECT region, COUNT(*) FROM sales GROUP BY region HAVING id > 0;")


def test_having_cannot_run_without_group_or_aggregate():
    engine = sales_engine()
    with pytest.raises(SqlqError):
        engine.execute("SELECT * FROM sales HAVING id > 0;")


def test_nested_aggregates_rejected():
    engine = sales_engine()
    with pytest.raises(SqlqError):
        engine.execute("SELECT COUNT(SUM(amount)) FROM sales;")


def test_aggregate_in_where_rejected():
    engine = sales_engine()
    with pytest.raises(SqlqError):
        engine.execute("SELECT * FROM sales WHERE COUNT(*) > 1;")


def test_distinct_aggregate():
    engine = sales_engine()
    assert engine.execute(
        "SELECT COUNT(DISTINCT region) FROM sales;").rows == [(3,)]
    result = engine.execute(
        "SELECT SUM(DISTINCT amount), AVG(DISTINCT amount) FROM sales;")
    assert result.rows == [(60, 15.0)]


def test_full_statement_where_group_having_order_limit():
    engine = sales_engine()
    result = engine.execute(
        "SELECT region, COUNT(*) AS n, SUM(amount) AS total FROM sales "
        "WHERE qty IS NOT NULL "
        "GROUP BY region HAVING SUM(amount) >= 0 "
        "ORDER BY total DESC LIMIT 2 OFFSET 0;")
    assert result.columns == ["region", "n", "total"]
    assert result.rows == [("east", 3, 30), ("north", 1, 0)]


def test_group_by_expression():
    engine = sales_engine()
    result = engine.execute(
        "SELECT amount > 15 AS big, COUNT(*) FROM sales "
        "WHERE amount IS NOT NULL GROUP BY amount > 15 ORDER BY big;")
    assert result.rows == [(False, 2), (True, 2)]
    assert result.columns == ["big", "COUNT(*)"]


def test_empty_grouped_result():
    engine = sales_engine()
    result = engine.execute(
        "SELECT region, COUNT(*) FROM sales WHERE id > 100 GROUP BY region;")
    assert result.rows == []


# ---------------------------------------------------------------------------
# DISTINCT
# ---------------------------------------------------------------------------

def test_distinct_single_column_with_null():
    engine = sales_engine()
    result = engine.execute(
        "SELECT DISTINCT amount FROM sales ORDER BY amount;")
    assert result.rows == [(None,), (0,), (10,), (20,), (30,)]


def test_distinct_multiple_columns():
    engine = Engine()
    engine.execute("CREATE TABLE t (a INTEGER, b INTEGER);")
    engine.execute_script(
        "INSERT INTO t VALUES (1,1); INSERT INTO t VALUES (1,1);"
        "INSERT INTO t VALUES (1,2);")
    assert engine.execute(
        "SELECT DISTINCT a, b FROM t ORDER BY a, b;").rows == [
        (1, 1), (1, 2)]


# ---------------------------------------------------------------------------
# ORDER BY / LIMIT / OFFSET
# ---------------------------------------------------------------------------

def test_order_by_multiple_columns_asc_desc():
    engine = sales_engine()
    result = engine.execute(
        "SELECT id, region, amount FROM sales "
        "ORDER BY region ASC, amount DESC, id ASC;")
    ids = [row[0] for row in result.rows]
    # ASC regions: east, north, west. DESC puts NULL first within each region.
    assert ids[:3] == [2, 1, 5]  # east: 20, 10, NULL
    assert ids[3] == 6           # north: 0
    assert ids[4:6] == [4, 3]    # west: 30 then NULL


def test_order_by_alias_and_ordinal():
    engine = sales_engine()
    by_alias = engine.execute(
        "SELECT region AS r, COUNT(*) FROM sales GROUP BY r ORDER BY r;")
    by_ordinal = engine.execute(
        "SELECT region AS r, COUNT(*) FROM sales GROUP BY r ORDER BY 1;")
    assert by_alias.rows == by_ordinal.rows
    assert by_alias.rows[0][0] == "east"


def test_order_by_ordinal_out_of_range():
    engine = sales_engine()
    with pytest.raises(SqlqError):
        engine.execute("SELECT id FROM sales ORDER BY 2;")
    with pytest.raises(SqlqError):
        engine.execute("SELECT id FROM sales ORDER BY 0;")


def test_order_by_expression_not_in_select():
    engine = sales_engine()
    result = engine.execute(
        "SELECT id FROM sales ORDER BY amount ASC, id ASC;")
    assert [row[0] for row in result.rows] == [3, 5, 6, 1, 2, 4]


def test_order_by_without_from_constant():
    engine = Engine()
    result = engine.execute("SELECT 1;")
    assert result.rows == [(1,)]


def test_limit_and_offset():
    engine = sales_engine()
    result = engine.execute(
        "SELECT id FROM sales ORDER BY id LIMIT 2 OFFSET 2;")
    assert result.rows == [(3,), (4,)]


def test_limit_zero_returns_no_rows():
    engine = sales_engine()
    assert engine.execute(
        "SELECT * FROM sales LIMIT 0;").rows == []


def test_offset_beyond_data_returns_empty():
    engine = sales_engine()
    assert engine.execute(
        "SELECT * FROM sales OFFSET 100;").rows == []


def test_offset_without_limit_is_allowed():
    engine = sales_engine()
    result = engine.execute(
        "SELECT id FROM sales ORDER BY id OFFSET 4;")
    assert result.rows == [(5,), (6,)]


# ---------------------------------------------------------------------------
# Misc edge cases
# ---------------------------------------------------------------------------

def test_select_without_from_constants():
    result = Engine().execute("SELECT 1 + 1 AS two, 'ok', NULL;")
    assert result.columns == ["two", "'ok'", "NULL"]
    assert result.rows == [(2, "ok", None)]


def test_select_constant_requires_no_aggregate_or_column():
    with pytest.raises(SqlqError):
        Engine().execute("SELECT COUNT(*);")
    with pytest.raises(SqlqError):
        Engine().execute("SELECT a;")


def test_where_row_order_stable_without_order_by():
    engine = sales_engine()
    assert engine.execute(
        "SELECT id FROM sales WHERE id > 2;").rows == [(3,), (4,), (5,), (6,)]
