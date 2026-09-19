import pytest

from sqlq import Engine, SqlqError


@pytest.fixture()
def engine(engine):
    engine.execute_script(
        """
        CREATE TABLE emp (
            id INTEGER PRIMARY KEY,
            name TEXT,
            dept TEXT,
            salary INTEGER,
            bonus INTEGER
        );
        INSERT INTO emp VALUES (1, 'alice', 'eng', 100, 10);
        INSERT INTO emp VALUES (2, 'bob',   'eng',  80, NULL);
        INSERT INTO emp VALUES (3, 'carol', 'sales', 90, 5);
        INSERT INTO emp VALUES (4, 'dave',  'sales', 70, NULL);
        INSERT INTO emp VALUES (5, 'erin',  NULL,   60, 6);
        """
    )
    return engine


# -- projection -------------------------------------------------------------

def test_select_star_uses_declared_order(engine):
    result = engine.execute("SELECT * FROM emp")
    assert result.columns == ["id", "name", "dept", "salary", "bonus"]
    assert result.rows[0] == (1, "alice", "eng", 100, 10)


def test_projection_and_aliases(engine):
    result = engine.execute(
        "SELECT name AS n, salary + 10 AS raised FROM emp WHERE id = 1"
    )
    assert result.columns == ["n", "raised"]
    assert result.rows == [("alice", 110)]


def test_default_expression_labels(engine):
    result = engine.execute("SELECT salary + bonus, salary > 80 FROM emp WHERE id = 1")
    assert result.columns == ["(salary + bonus)", "(salary > 80)"]


def test_constant_select_without_from(engine):
    assert engine.execute("SELECT 1 + 1").rows == [(2,)]
    assert engine.execute("SELECT 'hi'").columns == ["'hi'"]
    assert engine.execute("SELECT TRUE").rows == [(True,)]


def test_where_with_parenthesized_logic(engine):
    result = engine.execute(
        "SELECT name FROM emp WHERE (dept = 'eng' OR dept = 'sales') "
        "AND salary >= 90 ORDER BY name"
    )
    assert result.rows == [("alice",), ("carol",)]


def test_not_in_where(engine):
    result = engine.execute(
        "SELECT name FROM emp WHERE NOT salary >= 90 ORDER BY name"
    )
    assert result.rows == [("bob",), ("dave",), ("erin",)]


def test_string_dictionary_comparison(engine):
    result = engine.execute(
        "SELECT name FROM emp WHERE name >= 'b' ORDER BY name"
    )
    assert result.rows == [("bob",), ("carol",), ("dave",), ("erin",)]


# -- distinct ---------------------------------------------------------------

def test_distinct_single_column(engine):
    result = engine.execute("SELECT DISTINCT dept FROM emp ORDER BY dept")
    assert result.rows == [(None,), ("eng",), ("sales",)]


def test_distinct_treats_nulls_as_equal(engine):
    result = engine.execute("SELECT DISTINCT bonus FROM emp ORDER BY bonus")
    assert result.rows == [(None,), (5,), (6,), (10,)]


def test_distinct_multiple_columns(engine):
    engine.execute("INSERT INTO emp VALUES (6, 'frank', 'eng', 100, 10)")
    result = engine.execute(
        "SELECT DISTINCT dept, salary FROM emp ORDER BY salary"
    )
    assert ("eng", 100) in result.rows
    assert sum(1 for row in result.rows if row == ("eng", 100)) == 1


# -- ordering / paging ------------------------------------------------------

def test_order_by_multiple_columns_desc(engine):
    result = engine.execute(
        "SELECT name, salary FROM emp ORDER BY salary DESC, name ASC"
    )
    assert [row[1] for row in result.rows] == [100, 90, 80, 70, 60]
    assert result.rows[0][0] == "alice"


def test_order_by_alias(engine):
    result = engine.execute(
        "SELECT name, salary * 12 AS yearly FROM emp ORDER BY yearly LIMIT 2"
    )
    assert result.rows[0][0] == "erin"


def test_order_by_null_ordering(engine):
    asc = engine.execute("SELECT bonus FROM emp ORDER BY bonus ASC")
    assert asc.rows[0] == (None,)
    desc = engine.execute("SELECT bonus FROM emp ORDER BY bonus DESC")
    assert desc.rows[-1] == (None,)
    assert desc.rows[0] == (10,)


def test_limit_offset(engine):
    result = engine.execute(
        "SELECT id FROM emp ORDER BY id LIMIT 2 OFFSET 1"
    )
    assert result.rows == [(2,), (3,)]


def test_limit_only(engine):
    assert len(engine.execute("SELECT id FROM emp LIMIT 2").rows) == 2


def test_offset_beyond_end_returns_empty(engine):
    result = engine.execute("SELECT id FROM emp ORDER BY id LIMIT 5 OFFSET 100")
    assert result.rows == []


def test_limit_zero(engine):
    assert engine.execute("SELECT * FROM emp LIMIT 0").rows == []


def test_negative_limit_is_error(engine):
    with pytest.raises(SqlqError):
        engine.execute("SELECT * FROM emp LIMIT -1")


def test_non_integer_limit_is_error(engine):
    with pytest.raises(SqlqError):
        engine.execute("SELECT * FROM emp LIMIT 1.5")
