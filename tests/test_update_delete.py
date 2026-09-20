import pytest

from storelens import Engine, StorelensError


@pytest.fixture
def engine():
    e = Engine()
    e.execute_script("""
        CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT, v REAL);
        INSERT INTO t VALUES
            (1, 'a', 1.0), (2, 'b', 2.0), (3, 'c', 3.0);
    """)
    return e


def rows(engine):
    return engine.execute("SELECT * FROM t ORDER BY id;").rows


def test_update_with_where(engine):
    result = engine.execute("UPDATE t SET v = 99.0 WHERE id = 2;")
    assert result.affected == 1
    assert rows(engine) == [(1, "a", 1.0), (2, "b", 99.0), (3, "c", 3.0)]


def test_update_without_where_updates_all(engine):
    result = engine.execute("UPDATE t SET v = v * 10;")
    assert result.affected == 3
    assert [r[2] for r in rows(engine)] == [10.0, 20.0, 30.0]


def test_update_multiple_columns(engine):
    engine.execute("UPDATE t SET name = 'z', v = 0.5 WHERE id = 1;")
    assert rows(engine)[0] == (1, "z", 0.5)


def test_update_set_null(engine):
    engine.execute("UPDATE t SET v = NULL WHERE id = 1;")
    assert rows(engine)[0][2] is None


def test_update_uses_original_row_values(engine):
    engine.execute("UPDATE t SET v = v + 1 WHERE v >= 2;")
    assert [r[2] for r in rows(engine)] == [1.0, 3.0, 4.0]


def test_update_type_mismatch(engine):
    with pytest.raises(StorelensError, match="Type mismatch"):
        engine.execute("UPDATE t SET v = 'oops' WHERE id = 1;")


def test_update_unknown_column(engine):
    with pytest.raises(StorelensError, match="Unknown column"):
        engine.execute("UPDATE t SET nope = 1;")


def test_update_no_match(engine):
    result = engine.execute("UPDATE t SET v = 0 WHERE id = 999;")
    assert result.affected == 0
    assert len(rows(engine)) == 3


def test_delete_with_where(engine):
    result = engine.execute("DELETE FROM t WHERE v >= 2.0;")
    assert result.affected == 2
    assert rows(engine) == [(1, "a", 1.0)]


def test_delete_without_where_deletes_all(engine):
    result = engine.execute("DELETE FROM t;")
    assert result.affected == 3
    assert rows(engine) == []


def test_delete_no_match(engine):
    result = engine.execute("DELETE FROM t WHERE id = 999;")
    assert result.affected == 0
    assert len(rows(engine)) == 3


def test_delete_null_where_matches_nothing(engine):
    result = engine.execute("DELETE FROM t WHERE NULL;")
    assert result.affected == 0
