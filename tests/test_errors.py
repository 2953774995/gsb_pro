import pytest

from sqlq.errors import SqlqError
from sqlq.executor import Engine


def test_all_errors_are_sqlq_error():
    for sql in ("SELEC 1;", "SELECT * FROM;", "CREATE TABLE t (a BOGUS);",
                "INSERT INTO t VALUES (1);", "SELECT * FROM t",
                "SELECT (1 + 2;"):
        with pytest.raises(SqlqError):
            Engine().execute(sql)


def test_error_includes_position_for_syntax_issues():
    with pytest.raises(SqlqError) as info:
        Engine().execute("SELECT @ FROM t;")
    assert info.value.line == 1
    assert info.value.column == 8


def test_unknown_column_message_names_column():
    engine = Engine()
    engine.execute("CREATE TABLE t (a INTEGER);")
    with pytest.raises(SqlqError) as info:
        engine.execute("SELECT b FROM t;")
    assert "b" in str(info.value)


def test_unknown_table_message_names_table():
    with pytest.raises(SqlqError) as info:
        Engine().execute("SELECT * FROM orders;")
    assert "orders" in str(info.value)


def test_division_by_zero_is_sqlq_error():
    with pytest.raises(SqlqError):
        Engine().execute("SELECT 1 / 0;")
