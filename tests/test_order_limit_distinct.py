import pytest

from storelens import Engine


@pytest.fixture
def engine():
    e = Engine()
    e.execute_script("""
        CREATE TABLE t (id INTEGER PRIMARY KEY, g TEXT, v INTEGER);
        INSERT INTO t VALUES
            (1, 'b', 30), (2, 'a', 10), (3, 'b', 20),
            (4, 'a', 10), (5, 'c', 50), (6, 'b', 20);
    """)
    return e


def test_order_by_single_column(engine):
    result = engine.execute("SELECT id FROM t ORDER BY v DESC, id;")
    assert [r[0] for r in result.rows] == [5, 1, 3, 6, 2, 4]


def test_order_by_multiple_columns(engine):
    result = engine.execute(
        "SELECT id FROM t ORDER BY g ASC, v DESC, id ASC;")
    assert [r[0] for r in result.rows] == [2, 4, 1, 3, 6, 5]


def test_order_by_alias(engine):
    result = engine.execute(
        "SELECT id, v * 2 AS doubled FROM t ORDER BY doubled DESC LIMIT 1;")
    assert result.rows == [(5, 100)]


def test_order_by_expression(engine):
    # v % 20 -> ids 1,2,4,5 give 10; ids 3,6 give 0
    result = engine.execute(
        "SELECT id FROM t ORDER BY v % 20 DESC, id;")
    assert [r[0] for r in result.rows] == [1, 2, 4, 5, 3, 6]


def test_limit(engine):
    result = engine.execute("SELECT id FROM t ORDER BY id LIMIT 3;")
    assert result.rows == [(1,), (2,), (3,)]


def test_limit_offset(engine):
    result = engine.execute(
        "SELECT id FROM t ORDER BY id LIMIT 2 OFFSET 3;")
    assert result.rows == [(4,), (5,)]


def test_offset_beyond_end(engine):
    result = engine.execute(
        "SELECT id FROM t ORDER BY id LIMIT 5 OFFSET 100;")
    assert result.rows == []


def test_distinct(engine):
    result = engine.execute("SELECT DISTINCT g FROM t ORDER BY g;")
    assert result.rows == [("a",), ("b",), ("c",)]


def test_distinct_multiple_columns(engine):
    result = engine.execute("SELECT DISTINCT g, v FROM t ORDER BY g, v;")
    assert result.rows == [("a", 10), ("b", 20), ("b", 30), ("c", 50)]


def test_distinct_with_aggregates(engine):
    result = engine.execute(
        "SELECT DISTINCT g, COUNT(*) FROM t GROUP BY g ORDER BY g;")
    assert result.rows == [("a", 2), ("b", 3), ("c", 1)]
