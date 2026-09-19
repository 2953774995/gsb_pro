import pytest

from sqlq import Engine, SqlqError


def test_create_and_drop(engine):
    engine.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    assert "t" in engine.table_names()
    engine.execute("DROP TABLE t")
    assert "t" not in engine.table_names()


def test_create_duplicate_table(engine):
    engine.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SqlqError, match="already exists"):
        engine.execute("CREATE TABLE t (a INTEGER)")


def test_drop_unknown_table(engine):
    with pytest.raises(SqlqError, match="unknown table"):
        engine.execute("DROP TABLE nope")


def test_insert_full_row_and_select(engine):
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    result = engine.execute("INSERT INTO t VALUES (1, 'alice')")
    assert result.rowcount == 1
    rows = engine.execute("SELECT * FROM t").rows
    assert rows == [(1, "alice")]


def test_insert_partial_columns_default_null(engine):
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, a TEXT, b INTEGER)")
    engine.execute("INSERT INTO t (id, a) VALUES (1, 'x')")
    assert engine.execute("SELECT b FROM t").rows == [(None,)]


def test_insert_value_count_mismatch(engine):
    engine.execute("CREATE TABLE t (a INTEGER, b INTEGER)")
    with pytest.raises(SqlqError, match="values"):
        engine.execute("INSERT INTO t VALUES (1)")


def test_insert_unknown_column(engine):
    engine.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SqlqError):
        engine.execute("INSERT INTO t (b) VALUES (1)")


def test_primary_key_duplicate_rejected(engine):
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    engine.execute("INSERT INTO t VALUES (1, 'a')")
    with pytest.raises(SqlqError, match="primary key"):
        engine.execute("INSERT INTO t VALUES (1, 'b')")


def test_primary_key_null_rejected(engine):
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    with pytest.raises(SqlqError):
        engine.execute("INSERT INTO t (id) VALUES (NULL)")


def test_two_primary_keys_rejected(engine):
    with pytest.raises(SqlqError, match="PRIMARY KEY"):
        engine.execute(
            "CREATE TABLE t (a INTEGER PRIMARY KEY, b INTEGER PRIMARY KEY)"
        )


def test_integer_inserted_into_real_is_widened(engine):
    engine.execute("CREATE TABLE t (v REAL)")
    engine.execute("INSERT INTO t VALUES (3)")
    value = engine.execute("SELECT v FROM t").rows[0][0]
    assert value == 3.0 and isinstance(value, float)


def test_text_into_integer_is_type_mismatch(engine):
    engine.execute("CREATE TABLE t (v INTEGER)")
    with pytest.raises(SqlqError, match="type mismatch"):
        engine.execute("INSERT INTO t VALUES ('x')")


def test_integer_into_text_is_type_mismatch(engine):
    engine.execute("CREATE TABLE t (v TEXT)")
    with pytest.raises(SqlqError, match="type mismatch"):
        engine.execute("INSERT INTO t VALUES (1)")


def test_update_with_where(engine):
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER)")
    engine.execute("INSERT INTO t VALUES (1, 10)")
    engine.execute("INSERT INTO t VALUES (2, 20)")
    result = engine.execute("UPDATE t SET v = v + 1 WHERE id = 1")
    assert result.rowcount == 1
    assert engine.execute("SELECT v FROM t ORDER BY id").rows == [(11,), (20,)]


def test_update_without_where_covers_all_rows(engine):
    engine.execute("CREATE TABLE t (v INTEGER)")
    engine.execute("INSERT INTO t VALUES (1)")
    engine.execute("INSERT INTO t VALUES (2)")
    result = engine.execute("UPDATE t SET v = 0")
    assert result.rowcount == 2
    assert engine.execute("SELECT v FROM t").rows == [(0,), (0,)]


def test_update_primary_key_conflict(engine):
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    engine.execute("INSERT INTO t VALUES (1)")
    engine.execute("INSERT INTO t VALUES (2)")
    with pytest.raises(SqlqError, match="primary key"):
        engine.execute("UPDATE t SET id = 1 WHERE id = 2")


def test_update_unknown_column(engine):
    engine.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SqlqError):
        engine.execute("UPDATE t SET b = 1")


def test_delete_with_where(engine):
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    engine.execute("INSERT INTO t VALUES (1)")
    engine.execute("INSERT INTO t VALUES (2)")
    result = engine.execute("DELETE FROM t WHERE id = 1")
    assert result.rowcount == 1
    assert engine.execute("SELECT id FROM t").rows == [(2,)]


def test_delete_without_where_empties_table(engine):
    engine.execute("CREATE TABLE t (v INTEGER)")
    engine.execute("INSERT INTO t VALUES (1)")
    result = engine.execute("DELETE FROM t")
    assert result.rowcount == 1
    assert engine.execute("SELECT * FROM t").rows == []


def test_where_null_does_not_match(engine):
    engine.execute("CREATE TABLE t (v INTEGER)")
    engine.execute("INSERT INTO t VALUES (NULL)")
    assert engine.execute("SELECT * FROM t WHERE v = NULL").rows == []
    assert engine.execute("SELECT * FROM t WHERE v != 1").rows == []
    assert engine.execute("SELECT * FROM t WHERE v IS NULL").rows == [(None,)]


def test_execute_script_runs_every_statement(engine):
    results = engine.execute_script(
        "CREATE TABLE t (a INTEGER); INSERT INTO t VALUES (1); SELECT * FROM t;"
    )
    assert results[-1].rows == [(1,)]


def test_unknown_table_in_select(engine):
    with pytest.raises(SqlqError, match="unknown table"):
        engine.execute("SELECT * FROM missing")


def test_unknown_column_in_select(engine):
    engine.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SqlqError, match="unknown column"):
        engine.execute("SELECT b FROM t")


def test_rows_keep_insertion_order(engine):
    engine.execute("CREATE TABLE t (id INTEGER)")
    for i in range(5):
        engine.execute(f"INSERT INTO t VALUES ({i})")
    assert engine.execute("SELECT id FROM t").rows == [(i,) for i in range(5)]


def test_escaped_single_quote_round_trip(engine):
    engine.execute("CREATE TABLE t (s TEXT)")
    engine.execute("INSERT INTO t VALUES ('O''Brien')")
    assert engine.execute("SELECT s FROM t").rows == [("O'Brien",)]


def test_not_null_column_rejects_null_insert(engine):
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    engine.execute("INSERT INTO t VALUES (1, 'a')")
    with pytest.raises(SqlqError, match="NOT NULL"):
        engine.execute("INSERT INTO t (id) VALUES (2)")


def test_not_null_column_rejects_null_update(engine):
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    engine.execute("INSERT INTO t VALUES (1, 'a')")
    with pytest.raises(SqlqError, match="NOT NULL"):
        engine.execute("UPDATE t SET name = NULL WHERE id = 1")


def test_update_uses_original_row_for_self_referencing_values(engine):
    engine.execute("CREATE TABLE t (a INTEGER, b INTEGER)")
    engine.execute("INSERT INTO t VALUES (1, 10)")
    engine.execute("UPDATE t SET a = b, b = a + 100")
    assert engine.execute("SELECT a, b FROM t").rows == [(10, 101)]
