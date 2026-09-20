import pytest

from storelens import Engine


@pytest.fixture
def engine():
    e = Engine()
    e.execute_script("""
        CREATE TABLE t (id INTEGER PRIMARY KEY, a INTEGER, b INTEGER);
        INSERT INTO t VALUES (1, NULL, 1), (2, 5, 2), (3, NULL, 3);
    """)
    return e


def test_comparison_with_null_is_unknown_and_filtered(engine):
    # a = 5 is unknown for NULL rows -> they do not match WHERE
    result = engine.execute("SELECT id FROM t WHERE a = 5;")
    assert result.rows == [(2,)]
    result = engine.execute("SELECT id FROM t WHERE a != 5;")
    assert result.rows == []  # NULL != 5 is unknown, not true


def test_null_arithmetic_propagates(engine):
    result = engine.execute("SELECT a + b FROM t ORDER BY id;")
    assert result.rows == [(None,), (7,), (None,)]


def test_three_valued_and(engine):
    # FALSE AND NULL -> FALSE (row excluded); TRUE AND NULL -> NULL (excluded)
    result = engine.execute("SELECT id FROM t WHERE a IS NULL AND b > 100;")
    assert result.rows == []
    result = engine.execute("SELECT id FROM t WHERE a IS NULL AND b > 0 "
                            "ORDER BY id;")
    assert result.rows == [(1,), (3,)]


def test_three_valued_or(engine):
    # NULL OR TRUE -> TRUE
    result = engine.execute("SELECT id FROM t WHERE a = 5 OR b = 1;")
    assert result.rows == [(1,), (2,)]


def test_not_null_is_unknown(engine):
    # NOT (NULL comparison) is still unknown
    result = engine.execute("SELECT id FROM t WHERE NOT (a = 5);")
    assert result.rows == []


def test_aggregates_ignore_nulls(engine):
    result = engine.execute("SELECT COUNT(a), COUNT(*), SUM(a), AVG(a), "
                            "MIN(a), MAX(a) FROM t;")
    assert result.rows == [(1, 3, 5, 5.0, 5, 5)]


def test_sum_of_all_nulls_is_null(engine):
    engine.execute("DELETE FROM t WHERE a IS NOT NULL;")
    result = engine.execute("SELECT SUM(a), AVG(a), MIN(a), MAX(a), "
                            "COUNT(a), COUNT(*) FROM t;")
    assert result.rows == [(None, None, None, None, 0, 2)]


def test_group_by_nulls_form_one_group(engine):
    result = engine.execute(
        "SELECT a, COUNT(*) FROM t GROUP BY a ORDER BY a;")
    # NULL group sorts last
    assert result.rows == [(5, 1), (None, 2)]


def test_order_by_nulls_last(engine):
    result = engine.execute("SELECT id, a FROM t ORDER BY a, id;")
    assert result.rows == [(2, 5), (1, None), (3, None)]
    result = engine.execute("SELECT id, a FROM t ORDER BY a DESC, id;")
    assert result.rows == [(2, 5), (1, None), (3, None)]
