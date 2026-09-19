import pytest

from sqlq import Engine, SqlqError, ResultSet


@pytest.fixture()
def engine(engine):
    engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER, s TEXT)")
    return engine


def test_select_from_empty_table(engine):
    result = engine.execute("SELECT * FROM t")
    assert result.columns == ["id", "v", "s"]
    assert result.rows == []


def test_select_with_where_on_empty_table(engine):
    assert engine.execute("SELECT * FROM t WHERE v > 0").rows == []


def test_aggregate_on_empty_table_returns_single_row(engine):
    result = engine.execute(
        "SELECT COUNT(*), SUM(v), AVG(v), MIN(v), MAX(v) FROM t"
    )
    assert result.rows == [(0, None, None, None, None)]


def test_group_by_on_empty_table_returns_no_rows(engine):
    result = engine.execute("SELECT v, COUNT(*) FROM t GROUP BY v")
    assert result.rows == []


def test_distinct_on_empty_table(engine):
    assert engine.execute("SELECT DISTINCT v FROM t").rows == []


def test_order_by_limit_on_empty_table(engine):
    result = engine.execute("SELECT * FROM t ORDER BY v LIMIT 5 OFFSET 3")
    assert result.rows == []


def test_update_delete_on_empty_table(engine):
    assert engine.execute("UPDATE t SET v = 1").rowcount == 0
    assert engine.execute("DELETE FROM t").rowcount == 0


def test_all_null_rows_and_where(engine):
    engine.execute("INSERT INTO t (id) VALUES (1)")
    engine.execute("INSERT INTO t (id) VALUES (2)")
    assert engine.execute("SELECT COUNT(*) FROM t WHERE v IS NULL").rows == [(2,)]
    assert engine.execute("SELECT COUNT(v) FROM t").rows == [(0,)]
    assert engine.execute("SELECT SUM(v) FROM t").rows == [(None,)]


def test_result_set_as_dicts(engine):
    engine.execute("INSERT INTO t VALUES (1, 10, 'a')")
    result = engine.execute("SELECT id, v FROM t")
    assert isinstance(result, ResultSet)
    assert result.as_dicts() == [{"id": 1, "v": 10}]


def test_case_insensitive_keywords_and_function_names(engine):
    engine.execute("insert into t values (1, 10, 'a')")
    result = engine.execute("select count(*) from t where v = 10")
    assert result.rows == [(1,)]
    assert engine.execute("SeLeCt CoUnT(*) FrOm t").rows == [(1,)]


def test_string_escaped_quotes_in_predicate(engine):
    engine.execute("INSERT INTO t VALUES (1, 1, 'O''Reilly')")
    result = engine.execute("SELECT s FROM t WHERE s = 'O''Reilly'")
    assert result.rows == [("O'Reilly",)]


def test_float_literals_and_real_columns(engine):
    engine.execute("CREATE TABLE r (x REAL)")
    engine.execute("INSERT INTO r VALUES (1.5)")
    engine.execute("INSERT INTO r VALUES (2.25)")
    result = engine.execute("SELECT SUM(x), AVG(x) FROM r")
    assert result.rows == [(3.75, 1.875)]


def test_unknown_column_in_where(engine):
    with pytest.raises(SqlqError, match="unknown column"):
        engine.execute("SELECT * FROM t WHERE missing = 1")


def test_unknown_column_in_group_by(engine):
    with pytest.raises(SqlqError):
        engine.execute("SELECT COUNT(*) FROM t GROUP BY missing")


def test_bad_table_qualifier(engine):
    with pytest.raises(SqlqError):
        engine.execute("SELECT other.v FROM t")


def test_qualified_column_with_correct_table(engine):
    engine.execute("INSERT INTO t VALUES (1, 5, 'a')")
    assert engine.execute("SELECT t.v FROM t").rows == [(5,)]


def test_drop_and_recreate_table(engine):
    engine.execute("DROP TABLE t")
    engine.execute("CREATE TABLE t (a INTEGER)")
    engine.execute("INSERT INTO t VALUES (1)")
    assert engine.execute("SELECT a FROM t").rows == [(1,)]


def test_multiple_statements_share_state():
    engine = Engine()
    results = engine.execute_script(
        "CREATE TABLE n (x INTEGER);"
        "INSERT INTO n VALUES (1); INSERT INTO n VALUES (2);"
        "SELECT SUM(x) FROM n;"
    )
    assert results[-1].rows == [(3,)]


def test_script_error_aborts_and_message_clear():
    engine = Engine()
    with pytest.raises(SqlqError):
        engine.execute_script(
            "CREATE TABLE n (x INTEGER); INSERT INTO n VALUES (1); "
            "INSERT INTO n VALUES ('bad');"
        )


def test_select_with_every_clause(engine):
    engine.execute_script(
        """
        INSERT INTO t VALUES (1, 10, 'a');
        INSERT INTO t VALUES (2, 20, 'a');
        INSERT INTO t VALUES (3, 20, 'b');
        INSERT INTO t VALUES (4, 30, 'b');
        INSERT INTO t VALUES (5, 5,  'a');
        """
    )
    result = engine.execute(
        """
        SELECT s, COUNT(*) AS c, SUM(v) AS total
        FROM t
        WHERE id >= 1
        GROUP BY s
        HAVING SUM(v) > 20
        ORDER BY total DESC
        LIMIT 1
        """
    )
    assert result.rows == [("b", 2, 50)]


def test_null_string_comparison_unknown(engine):
    engine.execute("INSERT INTO t VALUES (1, NULL, NULL)")
    assert engine.execute("SELECT * FROM t WHERE s = NULL").rows == []
    assert engine.execute("SELECT * FROM t WHERE s <> NULL").rows == []
    assert engine.execute("SELECT * FROM t WHERE NOT s IS NULL").rows == []
    assert engine.execute("SELECT * FROM t WHERE s IS NULL").rows == [(1, None, None)]


def test_count_star_vs_count_column(engine):
    engine.execute("INSERT INTO t (id, s) VALUES (1, 'a')")
    engine.execute("INSERT INTO t (id, s) VALUES (2, NULL)")
    assert engine.execute("SELECT COUNT(*), COUNT(s), COUNT(v) FROM t").rows == [(2, 1, 0)]


def test_unknown_function_is_runtime_or_parse_error(engine):
    with pytest.raises(SqlqError):
        engine.execute("SELECT unknown_fn(1)")
