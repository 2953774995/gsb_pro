import json

import pytest

from storelens import Engine, StorelensError


@pytest.fixture
def engine():
    e = Engine()
    e.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price REAL);")
    return e


def write_json(tmp_path, data):
    path = tmp_path / "data.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_import_basic(engine, tmp_path):
    path = write_json(tmp_path, [
        {"id": 1, "name": "cola", "price": 3.5},
        {"id": 2, "name": "bread", "price": 2},
    ])
    count = engine.import_json("products", path)
    assert count == 2
    r = engine.execute("SELECT * FROM products ORDER BY id;")
    assert r.rows == [(1, "cola", 3.5), (2, "bread", 2.0)]


def test_import_missing_keys_become_null(engine, tmp_path):
    path = write_json(tmp_path, [{"id": 1, "name": "cola"}])
    engine.import_json("products", path)
    r = engine.execute("SELECT price FROM products;")
    assert r.rows == [(None,)]


def test_import_unknown_key_raises(engine, tmp_path):
    path = write_json(tmp_path, [{"id": 1, "name": "cola", "extra": 1}])
    with pytest.raises(StorelensError) as exc:
        engine.import_json("products", path)
    assert "extra" in str(exc.value)


def test_import_type_mismatch_raises(engine, tmp_path):
    path = write_json(tmp_path, [{"id": 1, "name": 42, "price": 1.0}])
    with pytest.raises(StorelensError) as exc:
        engine.import_json("products", path)
    assert "type mismatch" in str(exc.value)


def test_import_duplicate_primary_key_raises(engine, tmp_path):
    path = write_json(tmp_path, [
        {"id": 1, "name": "a", "price": 1.0},
        {"id": 1, "name": "b", "price": 2.0},
    ])
    with pytest.raises(StorelensError) as exc:
        engine.import_json("products", path)
    assert "primary key violation" in str(exc.value)


def test_import_non_array_raises(engine, tmp_path):
    path = write_json(tmp_path, {"id": 1})
    with pytest.raises(StorelensError) as exc:
        engine.import_json("products", path)
    assert "array of objects" in str(exc.value)


def test_import_non_object_element_raises(engine, tmp_path):
    path = write_json(tmp_path, [1, 2, 3])
    with pytest.raises(StorelensError):
        engine.import_json("products", path)


def test_import_unknown_table_raises(engine, tmp_path):
    path = write_json(tmp_path, [])
    with pytest.raises(StorelensError) as exc:
        engine.import_json("nope", path)
    assert "no such dataset" in str(exc.value)


def test_import_empty_array(engine, tmp_path):
    path = write_json(tmp_path, [])
    assert engine.import_json("products", path) == 0
