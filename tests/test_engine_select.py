import pytest

from storelens import Engine, StorelensError


@pytest.fixture
def engine():
    e = Engine()
    e.execute_script("""
        CREATE TABLE sales (
            id INTEGER PRIMARY KEY,
            store TEXT,
            product TEXT,
            amount REAL,
            qty INTEGER
        );
        INSERT INTO sales VALUES
            (1, 'A', 'cola',   10.5, 2),
            (2, 'B', 'bread',  20.0, 1),
            (3, 'A', 'bread',  NULL, 4),
            (4, 'B', 'cola',   5.25, 1),
            (5, 'A', 'cola',   7.0,  NULL),
            (6, NULL, 'bread', 3.0,  1);
    """)
    return e


def test_select_star_and_projection(engine):
    r = engine.execute("SELECT * FROM sales;")
    assert r.columns == ["id", "store", "product", "amount", "qty"]
    assert len(r.rows) == 6
    r = engine.execute("SELECT id, amount FROM sales WHERE id = 1;")
    assert r.columns == ["id", "amount"]
    assert r.rows == [(1, 10.5)]


def test_column_alias(engine):
    r = engine.execute("SELECT store AS shop, qty * 2 AS double_qty FROM sales WHERE id = 1;")
    assert r.columns == ["shop", "double_qty"]
    assert r.rows == [("A", 4)]


def test_where_comparison_and_logic(engine):
    r = engine.execute("SELECT id FROM sales WHERE qty >= 2 AND store = 'A';")
    assert r.rows == [(1,), (3,)]
    r = engine.execute("SELECT id FROM sales WHERE store = 'B' OR NOT (qty < 2);")
    assert r.rows == [(1,), (2,), (3,), (4,)]


def test_string_comparison_is_lexicographic(engine):
    r = engine.execute("SELECT id FROM sales WHERE product > 'bread';")
    assert r.rows == [(1,), (4,), (5,)]
    r = engine.execute("SELECT id FROM sales WHERE product <= 'bread';")
    assert r.rows == [(2,), (3,), (6,)]


def test_arithmetic_in_expressions(engine):
    r = engine.execute("SELECT amount + qty * 2 AS v FROM sales WHERE id = 1;")
    assert r.rows == [(14.5,)]
    r = engine.execute("SELECT -qty AS nq FROM sales WHERE id = 2;")
    assert r.rows == [(-1,)]


def test_null_comparison_never_matches(engine):
    # NULL = anything is unknown -> filtered out of WHERE
    r = engine.execute("SELECT id FROM sales WHERE amount = NULL;")
    assert r.rows == []
    r = engine.execute("SELECT id FROM sales WHERE amount != NULL;")
    assert r.rows == []


def test_null_arithmetic_propagates(engine):
    r = engine.execute("SELECT amount + 1 AS v FROM sales WHERE id = 3;")
    assert r.rows == [(None,)]


def test_is_null_is_not_null(engine):
    r = engine.execute("SELECT id FROM sales WHERE amount IS NULL;")
    assert r.rows == [(3,)]
    r = engine.execute("SELECT id FROM sales WHERE qty IS NOT NULL ORDER BY id;")
    assert r.rows == [(1,), (2,), (3,), (4,), (6,)]


def test_three_valued_logic_and_or(engine):
    # NULL AND FALSE -> FALSE (row excluded), NULL OR TRUE -> TRUE
    r = engine.execute("SELECT id FROM sales WHERE amount IS NULL AND qty > 100;")
    assert r.rows == []
    r = engine.execute("SELECT id FROM sales WHERE amount IS NULL OR id = 2;")
    assert r.rows == [(2,), (3,)]


def test_aggregates_ignore_nulls(engine):
    r = engine.execute("SELECT COUNT(*) AS n, COUNT(amount) AS na, "
                       "SUM(amount) AS s, AVG(qty) AS a, MIN(amount) AS mn, "
                       "MAX(amount) AS mx FROM sales;")
    n, na, s, a, mn, mx = r.rows[0]
    assert n == 6
    assert na == 5          # NULL amount not counted
    assert s == pytest.approx(45.75)
    assert a == pytest.approx(9 / 5)   # NULL qty skipped
    assert mn == 3.0 and mx == 20.0


def test_aggregates_over_empty_set(engine):
    r = engine.execute("SELECT COUNT(*) AS n, SUM(amount) AS s, AVG(amount) AS a "
                       "FROM sales WHERE id > 100;")
    assert r.rows == [(0, None, None)]


def test_group_by_and_having(engine):
    r = engine.execute("SELECT store, COUNT(*) AS n, SUM(amount) AS total "
                       "FROM sales GROUP BY store HAVING COUNT(*) > 1 "
                       "ORDER BY total DESC;")
    assert r.columns == ["store", "n", "total"]
    assert r.rows[0] == ("B", 2, 25.25)
    assert r.rows[1] == ("A", 3, 17.5)
    # NULL store forms its own group but has only 1 row -> filtered by HAVING
    assert all(row[0] is not None for row in r.rows)


def test_group_by_nulls_in_one_group(engine):
    engine.execute("INSERT INTO sales (id, store) VALUES (7, NULL);")
    r = engine.execute("SELECT store, COUNT(*) AS n FROM sales GROUP BY store;")
    null_groups = [row for row in r.rows if row[0] is None]
    assert null_groups == [(None, 2)]


def test_order_by_multi_column_and_direction(engine):
    r = engine.execute("SELECT id FROM sales ORDER BY store ASC, amount DESC;")
    # NULL store sorts first; within store, amount DESC
    assert r.rows == [(6,), (1,), (5,), (3,), (2,), (4,)]
    r = engine.execute("SELECT id FROM sales ORDER BY store DESC, id ASC;")
    assert r.rows == [(2,), (4,), (1,), (3,), (5,), (6,)]


def test_limit_and_offset(engine):
    r = engine.execute("SELECT id FROM sales ORDER BY id LIMIT 2;")
    assert r.rows == [(1,), (2,)]
    r = engine.execute("SELECT id FROM sales ORDER BY id LIMIT 2 OFFSET 2;")
    assert r.rows == [(3,), (4,)]
    r = engine.execute("SELECT id FROM sales ORDER BY id LIMIT 100 OFFSET 4;")
    assert r.rows == [(5,), (6,)]
    r = engine.execute("SELECT id FROM sales ORDER BY id LIMIT 0;")
    assert r.rows == []


def test_distinct(engine):
    r = engine.execute("SELECT DISTINCT store FROM sales ORDER BY store;")
    assert r.rows == [(None,), ("A",), ("B",)]
    r = engine.execute("SELECT DISTINCT product FROM sales WHERE store = 'A';")
    assert sorted(r.rows) == [("bread",), ("cola",)]


def test_combined_query(engine):
    # WHERE + GROUP BY + HAVING + ORDER BY + LIMIT in one statement
    r = engine.execute(
        "SELECT store, SUM(amount) AS total FROM sales "
        "WHERE product = 'cola' AND amount IS NOT NULL "
        "GROUP BY store HAVING SUM(amount) > 5 "
        "ORDER BY total DESC LIMIT 1 OFFSET 0;")
    assert r.rows == [("A", 17.5)]


def test_empty_table_select(engine):
    engine.execute("CREATE TABLE empty_t (a INTEGER, b TEXT);")
    r = engine.execute("SELECT * FROM empty_t;")
    assert r.columns == ["a", "b"]
    assert r.rows == []
    r = engine.execute("SELECT COUNT(*) AS n FROM empty_t;")
    assert r.rows == [(0,)]
    r = engine.execute("SELECT a, COUNT(*) FROM empty_t GROUP BY a;")
    assert r.rows == []


def test_empty_result_set_keeps_columns(engine):
    r = engine.execute("SELECT id, store FROM sales WHERE id = 999;")
    assert r.columns == ["id", "store"]
    assert r.rows == []


def test_order_by_alias(engine):
    r = engine.execute("SELECT store, SUM(amount) AS total FROM sales "
                       "GROUP BY store ORDER BY total DESC LIMIT 1;")
    assert r.rows == [("B", 25.25)]
