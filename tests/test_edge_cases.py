import pytest

from storelens import Engine, StorelensError


@pytest.fixture
def engine():
    return Engine()


def test_empty_table_select(engine):
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);")
    result = engine.execute("SELECT * FROM t;")
    assert result.columns == ["id", "v"]
    assert result.rows == []


def test_empty_result_set_keeps_columns(engine):
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    engine.execute("INSERT INTO t VALUES (1);")
    result = engine.execute("SELECT id FROM t WHERE id = 999;")
    assert result.columns == ["id"]
    assert result.rows == []


def test_group_by_on_empty_table(engine):
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, g TEXT);")
    result = engine.execute("SELECT g, COUNT(*) FROM t GROUP BY g;")
    assert result.rows == []


def test_distinct_on_empty_table(engine):
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    assert engine.execute("SELECT DISTINCT id FROM t;").rows == []


def test_execute_script_returns_results_in_order(engine):
    results = engine.execute_script("""
        CREATE TABLE t (id INTEGER PRIMARY KEY);
        INSERT INTO t VALUES (1), (2);
        SELECT COUNT(*) AS n FROM t;
    """)
    assert len(results) == 3
    assert results[2].rows == [(2,)]


def test_execute_script_stops_on_error(engine):
    with pytest.raises(StorelensError):
        engine.execute_script("""
            CREATE TABLE t (id INTEGER PRIMARY KEY);
            INSERT INTO missing VALUES (1);
            INSERT INTO t VALUES (1);
        """)
    # First statement committed, third never ran
    assert engine.execute("SELECT COUNT(*) FROM t;").rows == [(0,)]


def test_rows_keep_insertion_order(engine):
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    engine.execute("INSERT INTO t VALUES (3), (1), (2);")
    assert engine.execute("SELECT id FROM t;").rows == [(3,), (1,), (2,)]


def test_string_escaping_roundtrip(engine):
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, s TEXT);")
    engine.execute("INSERT INTO t VALUES (1, 'it''s');")
    assert engine.execute("SELECT s FROM t;").rows == [("it's",)]


def test_column_in_insert_values_rejected(engine):
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    with pytest.raises(StorelensError, match="cannot be referenced"):
        engine.execute("INSERT INTO t VALUES (id + 1);")


def test_null_literal_insert(engine):
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v REAL);")
    engine.execute("INSERT INTO t VALUES (1, NULL);")
    assert engine.execute("SELECT v FROM t;").rows == [(None,)]


def test_unary_minus(engine):
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER);")
    engine.execute("INSERT INTO t VALUES (1, 5);")
    result = engine.execute("SELECT -v, -v + 10 FROM t;")
    assert result.rows == [(-5, 5)]


def test_error_messages_are_descriptive(engine):
    with pytest.raises(StorelensError) as exc:
        engine.execute("SELEC 1;")
    assert "unknown statement keyword" in str(exc.value)
