import pytest

from storelens import Engine, StorelensError


@pytest.fixture
def engine():
    e = Engine()
    e.execute_script("""
        CREATE TABLE sales (
            id INTEGER PRIMARY KEY,
            store TEXT,
            category TEXT,
            amount REAL
        );
        INSERT INTO sales VALUES
            (1, 'A', 'food',  10.0),
            (2, 'A', 'drink', 4.0),
            (3, 'A', 'food',  6.0),
            (4, 'B', 'food',  20.0),
            (5, 'B', 'drink', NULL),
            (6, 'C', 'drink', 8.0);
    """)
    return e


def test_scalar_aggregates_whole_table(engine):
    result = engine.execute(
        "SELECT COUNT(*), COUNT(amount), SUM(amount), AVG(amount), "
        "MIN(amount), MAX(amount) FROM sales;")
    assert result.rows == [(6, 5, 48.0, 9.6, 4.0, 20.0)]


def test_group_by_single_column(engine):
    result = engine.execute(
        "SELECT store, COUNT(*) AS n, SUM(amount) AS total "
        "FROM sales GROUP BY store ORDER BY store;")
    assert result.rows == [("A", 3, 20.0), ("B", 2, 20.0), ("C", 1, 8.0)]


def test_group_by_multiple_columns(engine):
    result = engine.execute(
        "SELECT store, category, SUM(amount) AS total "
        "FROM sales GROUP BY store, category ORDER BY store, category;")
    assert result.rows == [
        ("A", "drink", 4.0), ("A", "food", 16.0),
        ("B", "drink", None), ("B", "food", 20.0),
        ("C", "drink", 8.0),
    ]


def test_having_filters_groups(engine):
    result = engine.execute(
        "SELECT store, SUM(amount) AS total FROM sales "
        "GROUP BY store HAVING SUM(amount) >= 20 ORDER BY store;")
    assert result.rows == [("A", 20.0), ("B", 20.0)]


def test_having_with_alias_expression(engine):
    result = engine.execute(
        "SELECT store, COUNT(*) AS n FROM sales "
        "GROUP BY store HAVING COUNT(*) > 1 ORDER BY n DESC, store;")
    assert result.rows == [("A", 3), ("B", 2)]


def test_aggregate_without_group_by_single_row(engine):
    result = engine.execute("SELECT COUNT(*) FROM sales;")
    assert result.rows == [(6,)]


def test_aggregate_on_empty_table(engine):
    engine.execute("CREATE TABLE empty (id INTEGER PRIMARY KEY, v REAL);")
    result = engine.execute("SELECT COUNT(*), SUM(v), AVG(v) FROM empty;")
    assert result.rows == [(0, None, None)]


def test_sum_on_text_column_fails(engine):
    with pytest.raises(StorelensError, match="Type mismatch"):
        engine.execute("SELECT SUM(store) FROM sales;")


def test_avg_on_text_column_fails(engine):
    with pytest.raises(StorelensError, match="Type mismatch"):
        engine.execute("SELECT AVG(category) FROM sales;")


def test_min_max_on_text(engine):
    result = engine.execute("SELECT MIN(store), MAX(store) FROM sales;")
    assert result.rows == [("A", "C")]


def test_unknown_function_fails(engine):
    with pytest.raises(StorelensError, match="Unknown function"):
        engine.execute("SELECT MEDIAN(amount) FROM sales;")


def test_aggregate_in_where_rejected(engine):
    with pytest.raises(StorelensError):
        engine.execute("SELECT id FROM sales WHERE SUM(amount) > 1;")


def test_where_group_having_order_limit_combined(engine):
    result = engine.execute("""
        SELECT store, COUNT(*) AS n, SUM(amount) AS total
        FROM sales
        WHERE amount IS NOT NULL
        GROUP BY store
        HAVING SUM(amount) >= 8
        ORDER BY total DESC, store ASC
        LIMIT 2 OFFSET 0;
    """)
    assert result.columns == ["store", "n", "total"]
    assert result.rows == [("A", 3, 20.0), ("B", 1, 20.0)]


def test_order_by_aggregate_not_in_select(engine):
    result = engine.execute(
        "SELECT store FROM sales GROUP BY store "
        "ORDER BY COUNT(*) DESC, store;")
    assert result.rows == [("A",), ("B",), ("C",)]
