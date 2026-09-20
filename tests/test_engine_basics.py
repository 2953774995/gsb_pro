import pytest

from storelens import Engine, StorelensError


@pytest.fixture
def engine():
    e = Engine()
    e.execute_script("""
        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            store TEXT,
            amount REAL,
            qty INTEGER
        );
        INSERT INTO orders VALUES
            (1, 'A', 10.5, 2),
            (2, 'A', 20.0, 1),
            (3, 'B', NULL, 4),
            (4, 'B', 5.0, NULL),
            (5, 'C', 7.5, 3);
    """)
    return e


# -- CREATE / DROP -----------------------------------------------------------

def test_create_and_list_tables(engine):
    assert engine.tables == ["orders"]


def test_create_duplicate_table_fails(engine):
    with pytest.raises(StorelensError, match="already exists"):
        engine.execute("CREATE TABLE orders (x INTEGER);")


def test_drop_table(engine):
    result = engine.execute("DROP TABLE orders;")
    assert "dropped" in result.message
    assert engine.tables == []
    with pytest.raises(StorelensError, match="Unknown table"):
        engine.execute("SELECT * FROM orders;")


def test_drop_unknown_table_fails(engine):
    with pytest.raises(StorelensError, match="Unknown table"):
        engine.execute("DROP TABLE ghost;")


def test_duplicate_column_definition_fails(engine):
    with pytest.raises(StorelensError, match="Duplicate column"):
        engine.execute("CREATE TABLE bad (a INTEGER, a TEXT);")


# -- INSERT / types ------------------------------------------------------------

def test_insert_type_coercion(engine):
    engine.execute("CREATE TABLE t (i INTEGER, r REAL, s TEXT);")
    engine.execute("INSERT INTO t VALUES (3.0, 2, 'x');")
    row = engine.execute("SELECT * FROM t;").rows[0]
    assert row == (3, 2.0, "x")
    assert isinstance(row[0], int)
    assert isinstance(row[1], float)


@pytest.mark.parametrize("value,col", [
    ("'abc'", "i"), ("1.5", "i"), ("'abc'", "r"), ("1", "s"),
])
def test_insert_type_mismatch(engine, value, col):
    engine.execute("CREATE TABLE t (i INTEGER, r REAL, s TEXT);")
    with pytest.raises(StorelensError, match="Type mismatch"):
        engine.execute("INSERT INTO t (%s) VALUES (%s);" % (col, value))


def test_insert_wrong_value_count(engine):
    with pytest.raises(StorelensError, match="expects 4 values"):
        engine.execute("INSERT INTO orders VALUES (9, 'A', 1.0);")


def test_insert_unknown_column(engine):
    with pytest.raises(StorelensError, match="Unknown column"):
        engine.execute("INSERT INTO orders (nope) VALUES (1);")


def test_insert_partial_columns_fills_null(engine):
    engine.execute("INSERT INTO orders (order_id, store) VALUES (9, 'Z');")
    row = engine.execute(
        "SELECT * FROM orders WHERE order_id = 9;").rows[0]
    assert row == (9, "Z", None, None)


# -- primary key ---------------------------------------------------------------

def test_primary_key_duplicate_rejected(engine):
    with pytest.raises(StorelensError, match="Primary key violation"):
        engine.execute("INSERT INTO orders VALUES (1, 'X', 1.0, 1);")


def test_primary_key_null_rejected(engine):
    with pytest.raises(StorelensError, match="cannot be NULL"):
        engine.execute("INSERT INTO orders VALUES (NULL, 'X', 1.0, 1);")


def test_primary_key_update_conflict(engine):
    with pytest.raises(StorelensError, match="Primary key violation"):
        engine.execute("UPDATE orders SET order_id = 2 WHERE order_id = 1;")


# -- SELECT projection -----------------------------------------------------------

def test_select_star(engine):
    result = engine.execute("SELECT * FROM orders ORDER BY order_id;")
    assert result.columns == ["order_id", "store", "amount", "qty"]
    assert len(result.rows) == 5


def test_select_columns_and_alias(engine):
    result = engine.execute(
        "SELECT store AS shop, qty * 2 AS double_qty FROM orders "
        "WHERE order_id = 1;")
    assert result.columns == ["shop", "double_qty"]
    assert result.rows == [("A", 4)]


def test_select_unknown_table(engine):
    with pytest.raises(StorelensError, match="Unknown table"):
        engine.execute("SELECT * FROM missing;")


def test_select_unknown_column(engine):
    with pytest.raises(StorelensError, match="Unknown column"):
        engine.execute("SELECT nope FROM orders;")


def test_case_insensitive_keywords_and_names(engine):
    result = engine.execute("select STORE from ORDERS where ORDER_ID = 1;")
    assert result.rows == [("A",)]


# -- WHERE expressions -----------------------------------------------------------

def test_where_comparisons(engine):
    result = engine.execute("SELECT order_id FROM orders WHERE qty >= 2 "
                            "ORDER BY order_id;")
    assert result.rows == [(1,), (3,), (5,)]


def test_where_string_comparison_lexicographic(engine):
    result = engine.execute(
        "SELECT order_id FROM orders WHERE store < 'B' ORDER BY order_id;")
    assert result.rows == [(1,), (2,)]


def test_where_and_or_not(engine):
    result = engine.execute(
        "SELECT order_id FROM orders "
        "WHERE NOT (store = 'A') AND (qty > 3 OR amount < 6.0) "
        "ORDER BY order_id;")
    assert result.rows == [(3,), (4,)]


def test_where_arithmetic(engine):
    result = engine.execute(
        "SELECT order_id FROM orders WHERE qty * 2 + 1 = 5;")
    assert result.rows == [(1,)]


def test_where_is_null(engine):
    result = engine.execute(
        "SELECT order_id FROM orders WHERE amount IS NULL;")
    assert result.rows == [(3,)]
    result = engine.execute(
        "SELECT order_id FROM orders WHERE amount IS NOT NULL "
        "ORDER BY order_id;")
    assert result.rows == [(1,), (2,), (4,), (5,)]


def test_compare_text_with_number_fails(engine):
    with pytest.raises(StorelensError, match="cannot compare"):
        engine.execute("SELECT order_id FROM orders WHERE store = 5;")


def test_arithmetic_on_text_fails(engine):
    with pytest.raises(StorelensError, match="requires numbers"):
        engine.execute("SELECT store + 1 FROM orders;")


def test_division_by_zero_fails(engine):
    with pytest.raises(StorelensError, match="Division by zero"):
        engine.execute("SELECT qty / 0 FROM orders;")


def test_execute_rejects_multiple_statements(engine):
    with pytest.raises(StorelensError, match="exactly one statement"):
        engine.execute("SELECT 1 FROM orders; SELECT 2 FROM orders;")
