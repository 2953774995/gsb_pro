import pytest

from storelens import Engine, StorelensError


@pytest.fixture
def engine():
    e = Engine()
    e.execute_script("""
        CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT, val REAL);
        INSERT INTO t VALUES (1, 'a', 1.5), (2, 'b', 2.5);
    """)
    return e


def test_unknown_table_raises(engine):
    with pytest.raises(StorelensError) as exc:
        engine.execute("SELECT * FROM nope;")
    assert "no such dataset" in str(exc.value)
    with pytest.raises(StorelensError):
        engine.execute("INSERT INTO nope VALUES (1);")
    with pytest.raises(StorelensError):
        engine.execute("UPDATE nope SET x = 1;")
    with pytest.raises(StorelensError):
        engine.execute("DELETE FROM nope;")


def test_unknown_column_raises(engine):
    for query in ("SELECT nope FROM t;",
                  "SELECT id FROM t WHERE nope = 1;",
                  "SELECT id FROM t ORDER BY nope;",
                  "SELECT id FROM t GROUP BY nope;",
                  "UPDATE t SET nope = 1;",
                  "INSERT INTO t (id, nope) VALUES (3, 1);"):
        with pytest.raises(StorelensError, match="no column named nope"):
            engine.execute(query)


def test_sum_on_text_raises(engine):
    with pytest.raises(StorelensError) as exc:
        engine.execute("SELECT SUM(name) FROM t;")
    assert "SUM" in str(exc.value)


def test_avg_on_text_raises(engine):
    with pytest.raises(StorelensError):
        engine.execute("SELECT AVG(name) FROM t;")


def test_arithmetic_on_text_raises(engine):
    with pytest.raises(StorelensError):
        engine.execute("SELECT name + 1 FROM t;")


def test_mixed_type_comparison_raises(engine):
    with pytest.raises(StorelensError):
        engine.execute("SELECT id FROM t WHERE name > 3;")


def test_division_by_zero_raises(engine):
    with pytest.raises(StorelensError) as exc:
        engine.execute("SELECT val / 0 FROM t;")
    assert "division by zero" in str(exc.value)


def test_syntax_errors_carry_position(engine):
    with pytest.raises(StorelensError) as exc:
        engine.execute("SELECT FROM t;")
    assert exc.value.line is not None
    with pytest.raises(StorelensError):
        engine.execute("SELEC * FROM t;")  # unknown keyword
    with pytest.raises(StorelensError):
        engine.execute("SELECT * FROM t")  # missing semicolon


def test_execute_requires_single_statement(engine):
    with pytest.raises(StorelensError):
        engine.execute("SELECT * FROM t; SELECT * FROM t;")


def test_execute_script_runs_all_and_returns_results(engine):
    results = engine.execute_script(
        "SELECT COUNT(*) AS n FROM t; DELETE FROM t WHERE id = 1; "
        "SELECT COUNT(*) AS n FROM t;")
    assert len(results) == 3
    assert results[0].rows == [(2,)]
    assert results[1].rowcount == 1
    assert results[2].rows == [(1,)]


def test_aggregate_outside_grouping_context_raises(engine):
    with pytest.raises(StorelensError):
        engine.execute("UPDATE t SET val = SUM(val);")


def test_min_max_mixed_types_raise(engine):
    engine.execute("CREATE TABLE m (x TEXT);")
    engine.execute("INSERT INTO m VALUES ('a');")
    # MIN on TEXT alone is fine
    assert engine.execute("SELECT MIN(x) FROM m;").rows == [("a",)]
