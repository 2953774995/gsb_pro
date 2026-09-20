import json

import pytest

from storelens import Engine, StorelensError


@pytest.fixture
def engine():
    e = Engine()
    e.execute("""
        CREATE TABLE products (
            sku INTEGER PRIMARY KEY,
            name TEXT,
            price REAL
        );
    """)
    return e


def write_json(tmp_path, data):
    path = tmp_path / "data.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_import_from_file(engine, tmp_path):
    path = write_json(tmp_path, [
        {"sku": 1, "name": "cola", "price": 3.5},
        {"sku": 2, "name": "bread", "price": 2.0},
    ])
    count = engine.import_json("products", path)
    assert count == 2
    result = engine.execute("SELECT * FROM products ORDER BY sku;")
    assert result.rows == [(1, "cola", 3.5), (2, "bread", 2.0)]


def test_import_from_parsed_list(engine):
    count = engine.import_json("products", [{"sku": 9, "name": "milk",
                                             "price": 5.0}])
    assert count == 1


def test_import_missing_columns_become_null(engine, tmp_path):
    path = write_json(tmp_path, [{"sku": 1, "name": "cola"}])
    engine.import_json("products", path)
    assert engine.execute("SELECT price FROM products;").rows == [(None,)]


def test_import_unknown_column_fails(engine, tmp_path):
    path = write_json(tmp_path, [{"sku": 1, "name": "x", "extra": 1}])
    with pytest.raises(StorelensError, match="unknown column"):
        engine.import_json("products", path)


def test_import_duplicate_primary_key_fails_and_is_atomic(engine, tmp_path):
    path = write_json(tmp_path, [
        {"sku": 1, "name": "a", "price": 1.0},
        {"sku": 1, "name": "b", "price": 2.0},
    ])
    with pytest.raises(StorelensError, match="Primary key violation"):
        engine.import_json("products", path)
    # Table unchanged after failed import
    assert engine.execute("SELECT COUNT(*) FROM products;").rows == [(0,)]


def test_import_conflicts_with_existing_rows(engine, tmp_path):
    engine.execute("INSERT INTO products VALUES (1, 'a', 1.0);")
    path = write_json(tmp_path, [{"sku": 1, "name": "b", "price": 2.0}])
    with pytest.raises(StorelensError, match="Primary key violation"):
        engine.import_json("products", path)


def test_import_type_mismatch(engine, tmp_path):
    path = write_json(tmp_path, [{"sku": 1, "name": "a", "price": "cheap"}])
    with pytest.raises(StorelensError, match="Type mismatch"):
        engine.import_json("products", path)


def test_import_invalid_json_file(engine, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(StorelensError, match="Invalid JSON"):
        engine.import_json("products", str(path))


def test_import_missing_file(engine):
    with pytest.raises(StorelensError, match="not found"):
        engine.import_json("products", "/nonexistent/file.json")


def test_import_non_array_fails(engine, tmp_path):
    path = write_json(tmp_path, {"sku": 1})
    with pytest.raises(StorelensError, match="array of objects"):
        engine.import_json("products", path)


def test_import_unknown_table(engine, tmp_path):
    path = write_json(tmp_path, [])
    with pytest.raises(StorelensError, match="Unknown table"):
        engine.import_json("nope", path)
