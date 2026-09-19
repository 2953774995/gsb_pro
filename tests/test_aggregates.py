import pytest

from sqlq import Engine, SqlqError


@pytest.fixture()
def sales(engine):
    engine.execute_script(
        """
        CREATE TABLE sales (id INTEGER PRIMARY KEY, region TEXT,
                            amount INTEGER, qty REAL);
        INSERT INTO sales VALUES (1, 'east', 10, 1.0);
        INSERT INTO sales VALUES (2, 'east', 20, 2.0);
        INSERT INTO sales VALUES (3, 'west', 30, 3.0);
        INSERT INTO sales VALUES (4, 'west', NULL, 4.0);
        INSERT INTO sales VALUES (5, NULL, 40, NULL);
        """
    )
    return engine


def test_count_star_counts_all_rows(sales):
    assert sales.execute("SELECT COUNT(*) FROM sales").rows == [(5,)]


def test_count_column_ignores_null(sales):
    assert sales.execute("SELECT COUNT(amount) FROM sales").rows == [(4,)]
    assert sales.execute("SELECT COUNT(qty) FROM sales").rows == [(4,)]


def test_count_distinct(sales):
    sales.execute("INSERT INTO sales VALUES (6, 'east', 10, 1.0)")
    result = sales.execute("SELECT COUNT(DISTINCT amount) FROM sales")
    assert result.rows == [(4,)]  # 10,20,30,40 (NULL ignored)


def test_sum_avg_min_max_basic(sales):
    assert sales.execute("SELECT SUM(amount) FROM sales").rows == [(100,)]
    result = sales.execute("SELECT AVG(amount) FROM sales").rows[0][0]
    assert result == 25.0
    assert sales.execute("SELECT MIN(amount), MAX(amount) FROM sales").rows == [(10, 40)]


def test_sum_skips_null(sales):
    # 10+20+30+40 = 100 (the NULL row is skipped)
    assert sales.execute("SELECT SUM(amount) FROM sales").rows == [(100,)]


def test_avg_skips_null(sales):
    assert sales.execute("SELECT AVG(amount) FROM sales").rows == [(25.0,)]


def test_min_max_on_text_uses_dictionary_order(sales):
    result = sales.execute("SELECT MIN(region), MAX(region) FROM sales")
    assert result.rows == [("east", "west")]


def test_aggregate_over_empty_set(sales):
    result = sales.execute("SELECT COUNT(*), SUM(amount), AVG(amount), "
                           "MIN(amount), MAX(amount) FROM sales WHERE id > 100")
    assert result.rows == [(0, None, None, None, None)]


def test_group_by_basic(sales):
    result = sales.execute(
        "SELECT region, COUNT(*), SUM(amount) FROM sales "
        "GROUP BY region ORDER BY region"
    )
    assert result.rows == [
        (None, 1, 40),
        ("east", 2, 30),
        ("west", 2, 30),
    ]


def test_group_by_null_is_one_group(sales):
    result = sales.execute(
        "SELECT region, COUNT(*) FROM sales GROUP BY region HAVING region IS NULL"
    )
    assert result.rows == [(None, 1)]


def test_having_filters_groups(sales):
    result = sales.execute(
        "SELECT region, SUM(amount) AS total FROM sales "
        "GROUP BY region HAVING SUM(amount) > 30"
    )
    assert result.rows == [(None, 40)]


def test_having_alias_not_supported_but_expression_works(sales):
    result = sales.execute(
        "SELECT region, COUNT(*) AS c FROM sales GROUP BY region "
        "HAVING COUNT(*) >= 2 ORDER BY region"
    )
    assert result.rows == [("east", 2), ("west", 2)]


def test_aggregate_with_where_group_having_order_limit(sales):
    result = sales.execute(
        """
        SELECT region, AVG(amount) AS avg_amount, COUNT(*) AS n
        FROM sales
        WHERE id <= 4
        GROUP BY region
        HAVING COUNT(*) = 2
        ORDER BY avg_amount DESC
        LIMIT 1
        """
    )
    assert result.columns == ["region", "avg_amount", "n"]
    # id <= 4: east (10,20)->avg 15; west (30,NULL)->avg 30 (NULL skipped)
    assert result.rows == [("west", 30.0, 2)]


def test_avg_ignores_null_in_group(sales):
    result = sales.execute(
        "SELECT region, AVG(amount) FROM sales GROUP BY region ORDER BY region"
    )
    # ASC order: NULL group first, then east, west.
    assert result.rows == [(None, 40.0), ("east", 15.0), ("west", 30.0)]


def test_grand_aggregate_with_no_group_by(sales):
    result = sales.execute("SELECT MAX(amount), MIN(amount) FROM sales")
    assert result.rows == [(40, 10)]


def test_aggregate_in_where_is_rejected(sales):
    with pytest.raises(SqlqError, match="WHERE"):
        sales.execute("SELECT * FROM sales WHERE COUNT(*) > 1")


def test_nested_aggregate_rejected(sales):
    with pytest.raises(SqlqError, match="nested aggregate"):
        sales.execute("SELECT SUM(COUNT(*)) FROM sales")


def test_bare_column_without_group_by_rejected(sales):
    with pytest.raises(SqlqError, match="GROUP BY"):
        sales.execute("SELECT region, COUNT(*) FROM sales")


def test_group_by_column_not_selected_is_ok(sales):
    result = sales.execute("SELECT SUM(amount) FROM sales GROUP BY region")
    assert len(result.rows) == 3


def test_sum_on_text_column_is_type_error(sales):
    with pytest.raises(SqlqError, match="TEXT"):
        sales.execute("SELECT SUM(region) FROM sales")


def test_avg_on_text_column_is_type_error(sales):
    with pytest.raises(SqlqError, match="TEXT"):
        sales.execute("SELECT AVG(region) FROM sales")


def test_min_on_text_allowed(sales):
    assert sales.execute("SELECT MIN(region) FROM sales").rows == [("east",)]


def test_order_by_aggregate(sales):
    result = sales.execute(
        "SELECT region, SUM(amount) FROM sales GROUP BY region "
        "ORDER BY SUM(amount) DESC, region ASC"
    )
    assert result.rows[0] == (None, 40)
    assert result.rows[1:] == [("east", 30), ("west", 30)]


def test_distinct_aggregate(sales):
    sales.execute("INSERT INTO sales VALUES (6, 'east', 10, 1.0)")
    assert sales.execute("SELECT SUM(DISTINCT amount) FROM sales").rows == [(100,)]
    assert sales.execute("SELECT COUNT(DISTINCT region) FROM sales").rows == [(2,)]


def test_group_by_multiple_columns(sales):
    engine = sales
    engine.execute("CREATE TABLE t (a TEXT, b TEXT, v INTEGER)")
    engine.execute("INSERT INTO t VALUES ('x', 'p', 1)")
    engine.execute("INSERT INTO t VALUES ('x', 'p', 2)")
    engine.execute("INSERT INTO t VALUES ('x', 'q', 3)")
    result = engine.execute(
        "SELECT a, b, SUM(v) FROM t GROUP BY a, b ORDER BY b"
    )
    assert result.rows == [("x", "p", 3), ("x", "q", 3)]
