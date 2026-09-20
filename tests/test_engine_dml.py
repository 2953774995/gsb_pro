import pytest

from storelens import Engine, StorelensError


@pytest.fixture
def engine():
    e = Engine()
    e.execute_script("""
        CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, price REAL, stock INTEGER);
        INSERT INTO items VALUES
            (1, 'cola', 3.5, 10),
            (2, 'bread', 2.0, 5),
            (3, 'milk', 4.25, NULL);
    """)
    return e


def test_create_and_drop_table(engine):
    assert "items" in engine.tables
    engine.execute("CREATE TABLE tmp (x INTEGER);")
    assert "tmp" in engine.tables
    engine.execute("DROP TABLE tmp;")
    assert "tmp" not in engine.tables
    with pytest.raises(StorelensError):
        engine.execute("DROP TABLE tmp;")


def test_create_duplicate_table_raises(engine):
    with pytest.raises(StorelensError) as exc:
        engine.execute("CREATE TABLE items (x INTEGER);")
    assert "already exists" in str(exc.value)


def test_insert_with_column_list_and_defaults(engine):
    engine.execute("INSERT INTO items (id, name) VALUES (4, 'gum');")
    r = engine.execute("SELECT price, stock FROM items WHERE id = 4;")
    assert r.rows == [(None, None)]


def test_insert_wrong_arity_raises(engine):
    with pytest.raises(StorelensError) as exc:
        engine.execute("INSERT INTO items VALUES (5, 'x');")
    assert "2 values for 4 columns" in str(exc.value)


def test_insert_type_mismatch_raises(engine):
    with pytest.raises(StorelensError) as exc:
        engine.execute("INSERT INTO items VALUES (5, 'x', 'not-a-number', 1);")
    assert "type mismatch" in str(exc.value)
    with pytest.raises(StorelensError):
        engine.execute("INSERT INTO items VALUES (5, 'x', 1.5, 1.5);")


def test_real_column_accepts_int_and_coerces(engine):
    engine.execute("INSERT INTO items VALUES (5, 'x', 3, 1);")
    r = engine.execute("SELECT price FROM items WHERE id = 5;")
    assert r.rows == [(3.0,)]
    assert isinstance(r.rows[0][0], float)


def test_primary_key_conflict_raises(engine):
    with pytest.raises(StorelensError) as exc:
        engine.execute("INSERT INTO items VALUES (1, 'dup', 1.0, 1);")
    assert "primary key violation" in str(exc.value)
    # failed insert must not corrupt existing data
    assert engine.execute("SELECT COUNT(*) AS n FROM items;").rows == [(3,)]


def test_primary_key_null_raises(engine):
    with pytest.raises(StorelensError):
        engine.execute("INSERT INTO items (name) VALUES ('no-id');")


def test_update_with_where(engine):
    result = engine.execute("UPDATE items SET stock = stock + 5 WHERE name = 'cola';")
    assert result.rowcount == 1
    r = engine.execute("SELECT stock FROM items WHERE id = 1;")
    assert r.rows == [(15,)]


def test_update_without_where_touches_all_rows(engine):
    result = engine.execute("UPDATE items SET price = price * 2;")
    assert result.rowcount == 3
    r = engine.execute("SELECT price FROM items ORDER BY id;")
    assert r.rows == [(7.0,), (4.0,), (8.5,)]


def test_update_where_matches_nothing(engine):
    result = engine.execute("UPDATE items SET stock = 0 WHERE id = 999;")
    assert result.rowcount == 0


def test_update_null_semantics(engine):
    # stock IS NULL row: stock + 1 stays NULL
    engine.execute("UPDATE items SET stock = stock + 1 WHERE id = 3;")
    assert engine.execute("SELECT stock FROM items WHERE id = 3;").rows == [(None,)]


def test_update_primary_key_conflict_raises(engine):
    with pytest.raises(StorelensError):
        engine.execute("UPDATE items SET id = 2 WHERE id = 1;")


def test_update_type_mismatch_raises(engine):
    with pytest.raises(StorelensError):
        engine.execute("UPDATE items SET stock = 'many' WHERE id = 1;")


def test_delete_with_where(engine):
    result = engine.execute("DELETE FROM items WHERE stock IS NULL;")
    assert result.rowcount == 1
    r = engine.execute("SELECT id FROM items ORDER BY id;")
    assert r.rows == [(1,), (2,)]


def test_delete_without_where_clears_table(engine):
    result = engine.execute("DELETE FROM items;")
    assert result.rowcount == 3
    assert engine.execute("SELECT COUNT(*) AS n FROM items;").rows == [(0,)]


def test_delete_nothing_matches(engine):
    result = engine.execute("DELETE FROM items WHERE id > 100;")
    assert result.rowcount == 0


def test_row_order_is_insertion_order(engine):
    r = engine.execute("SELECT id FROM items;")
    assert r.rows == [(1,), (2,), (3,)]
    engine.execute("DELETE FROM items WHERE id = 1;")
    engine.execute("INSERT INTO items VALUES (9, 'late', 1.0, 1);")
    r = engine.execute("SELECT id FROM items;")
    assert r.rows == [(2,), (3,), (9,)]
