import pytest

from sqlq.errors import SqlqError
from sqlq.executor import Engine


def make_engine():
    engine = Engine()
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT, score REAL);")
    return engine


def test_create_and_drop_table_lifecycle():
    engine = Engine()
    engine.execute("CREATE TABLE t (a INTEGER);")
    engine.execute("DROP TABLE t;")
    with pytest.raises(SqlqError):
        engine.execute("SELECT * FROM t;")


def test_create_duplicate_table():
    engine = Engine()
    engine.execute("CREATE TABLE t (a INTEGER);")
    with pytest.raises(SqlqError):
        engine.execute("CREATE TABLE t (b TEXT);")


def test_drop_unknown_table():
    with pytest.raises(SqlqError):
        Engine().execute("DROP TABLE nope;")


def test_insert_and_select_all_columns():
    engine = make_engine()
    engine.execute("INSERT INTO t VALUES (1, 'ann', 9.5);")
    result = engine.execute("SELECT * FROM t;")
    assert result.columns == ["id", "name", "score"]
    assert result.rows == [(1, "ann", 9.5)]


def test_insert_partial_columns_rest_null():
    engine = make_engine()
    engine.execute("INSERT INTO t (id, name) VALUES (7, 'bob');")
    result = engine.execute("SELECT score FROM t WHERE id = 7;")
    assert result.rows == [(None,)]


def test_insert_wrong_value_count():
    engine = make_engine()
    with pytest.raises(SqlqError):
        engine.execute("INSERT INTO t VALUES (1, 'ann');")
    with pytest.raises(SqlqError):
        engine.execute("INSERT INTO t (id, name) VALUES (1);")


def test_insert_unknown_column():
    engine = make_engine()
    with pytest.raises(SqlqError):
        engine.execute("INSERT INTO t (nope) VALUES (1);")


def test_type_coercion_integer_to_real_and_type_errors():
    engine = make_engine()
    engine.execute("INSERT INTO t VALUES (1, 'a', 2);")
    assert engine.execute("SELECT score FROM t;").rows == [(2.0,)]
    with pytest.raises(SqlqError):
        engine.execute("INSERT INTO t VALUES ('x', 'a', 1.0);")
    with pytest.raises(SqlqError):
        engine.execute("INSERT INTO t VALUES (2, 3, 1.0);")


def test_primary_key_duplicate_rejected():
    engine = make_engine()
    engine.execute("INSERT INTO t VALUES (1, 'a', 1.0);")
    with pytest.raises(SqlqError) as info:
        engine.execute("INSERT INTO t VALUES (1, 'b', 2.0);")
    assert "primary key violation" in str(info.value)


def test_primary_key_null_rejected():
    engine = make_engine()
    with pytest.raises(SqlqError):
        engine.execute("INSERT INTO t (name) VALUES ('a');")


def test_update_specific_rows_and_rowcount():
    engine = make_engine()
    engine.execute_script(
        "INSERT INTO t VALUES (1,'a',1.0);"
        "INSERT INTO t VALUES (2,'a',2.0);"
        "INSERT INTO t VALUES (3,'b',3.0);")
    result = engine.execute("UPDATE t SET score = score + 10 WHERE name = 'a';")
    assert result.rowcount == 2
    assert engine.execute("SELECT score FROM t ORDER BY id;").rows == [
        (11.0,), (12.0,), (3.0,)]


def test_update_without_where_updates_all_rows():
    engine = make_engine()
    engine.execute_script(
        "INSERT INTO t VALUES (1,'a',1.0); INSERT INTO t VALUES (2,'b',2.0);")
    result = engine.execute("UPDATE t SET score = 0;")
    assert result.rowcount == 2
    assert engine.execute("SELECT COUNT(*) FROM t;").rows == [(2,)]


def test_update_unknown_column_and_value_type_error():
    engine = make_engine()
    engine.execute("INSERT INTO t VALUES (1,'a',1.0);")
    with pytest.raises(SqlqError):
        engine.execute("UPDATE t SET nope = 1;")
    with pytest.raises(SqlqError):
        engine.execute("UPDATE t SET name = 5 WHERE id = 1;")


def test_update_primary_key_conflict():
    engine = make_engine()
    engine.execute_script(
        "INSERT INTO t VALUES (1,'a',1.0); INSERT INTO t VALUES (2,'b',2.0);")
    with pytest.raises(SqlqError):
        engine.execute("UPDATE t SET id = 1 WHERE id = 2;")


def test_update_primary_key_to_same_value_allowed():
    engine = make_engine()
    engine.execute("INSERT INTO t VALUES (1,'a',1.0);")
    engine.execute("UPDATE t SET id = 1 WHERE id = 1;")
    assert engine.execute("SELECT id FROM t;").rows == [(1,)]


def test_delete_with_where():
    engine = make_engine()
    engine.execute_script(
        "INSERT INTO t VALUES (1,'a',1.0); INSERT INTO t VALUES (2,'b',2.0);")
    result = engine.execute("DELETE FROM t WHERE name = 'a';")
    assert result.rowcount == 1
    assert engine.execute("SELECT id FROM t;").rows == [(2,)]


def test_delete_without_where_empties_table():
    engine = make_engine()
    engine.execute_script(
        "INSERT INTO t VALUES (1,'a',1.0); INSERT INTO t VALUES (2,'b',2.0);")
    result = engine.execute("DELETE FROM t;")
    assert result.rowcount == 2
    assert engine.execute("SELECT * FROM t;").rows == []


def test_delete_unknown_table():
    with pytest.raises(SqlqError):
        Engine().execute("DELETE FROM nope WHERE x = 1;")


def test_rows_retain_insertion_order():
    engine = make_engine()
    for i in (3, 1, 2):
        engine.execute(
            "INSERT INTO t VALUES ({}, 'n{}', 1.0);".format(i, i))
    assert engine.execute("SELECT id FROM t;").rows == [(3,), (1,), (2,)]


def test_execute_rejects_multiple_statements():
    engine = make_engine()
    with pytest.raises(SqlqError):
        engine.execute("SELECT 1; SELECT 2;")


def test_execute_script_returns_every_result():
    engine = Engine()
    results = engine.execute_script(
        "CREATE TABLE u (a INTEGER); INSERT INTO u VALUES (1); SELECT * FROM u;")
    assert [r.statement for r in results] == [
        "CREATE TABLE", "INSERT", "SELECT"]
    assert results[-1].rows == [(1,)]


def test_identifiers_and_keywords_are_case_insensitive():
    engine = Engine()
    engine.execute("create table Mix (A integer primary key, B text);")
    engine.execute("insert into mix (a, b) values (1, 'x');")
    assert engine.execute("select A, b from MIX;").rows == [(1, "x")]
