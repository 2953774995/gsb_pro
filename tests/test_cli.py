import io

import pytest

from storelens import Engine
from storelens.cli import Shell, format_table, main
from storelens.engine import Result


def test_format_table_alignment():
    result = Result(columns=["id", "name"],
                    rows=[(1, "cola"), (20, "bread")])
    text = format_table(result)
    lines = text.splitlines()
    assert lines[0] == "id | name "
    assert lines[1] == "---+------"
    assert lines[2] == "1  | cola "
    assert lines[3] == "20 | bread"
    assert "(2 rows)" in text


def test_format_table_null_and_float():
    result = Result(columns=["v"], rows=[(None,), (3.5,)])
    text = format_table(result)
    assert "NULL" in text
    assert "3.5" in text


def test_format_table_message_only():
    assert format_table(Result(message="OK")) == "OK"


def test_shell_meta_commands():
    out = io.StringIO()
    shell = Shell(Engine(), out=out)
    shell.engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, s TEXT);")
    shell.handle_meta(".tables")
    assert "t" in out.getvalue()
    shell.handle_meta(".schema t")
    assert "id INTEGER PRIMARY KEY" in out.getvalue()
    assert shell.handle_meta(".exit") is False


def test_shell_import_meta(tmp_path):
    path = tmp_path / "rows.json"
    path.write_text('[{"id": 1, "s": "x"}]', encoding="utf-8")
    out = io.StringIO()
    shell = Shell(Engine(), out=out)
    shell.engine.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, s TEXT);")
    shell.handle_meta(".import t %s" % path)
    assert "1 row(s) imported" in out.getvalue()
    assert shell.engine.execute("SELECT * FROM t;").rows == [(1, "x")]


def test_run_text_prints_results():
    out = io.StringIO()
    shell = Shell(Engine(), out=out)
    shell.run_text("CREATE TABLE t (id INTEGER PRIMARY KEY);"
                   "INSERT INTO t VALUES (1); SELECT * FROM t;")
    text = out.getvalue()
    assert "created" in text
    assert "inserted" in text
    assert "id" in text and "1" in text


def test_main_with_script_file(tmp_path, capsys):
    script = tmp_path / "demo.sql"
    script.write_text("""
        CREATE TABLE t (id INTEGER PRIMARY KEY, v REAL);
        INSERT INTO t VALUES (1, 2.5);
        SELECT * FROM t;
    """, encoding="utf-8")
    assert main([str(script)]) == 0
    out = capsys.readouterr().out
    assert "2.5" in out


def test_main_script_error_returns_1(tmp_path, capsys):
    script = tmp_path / "bad.sql"
    script.write_text("SELECT * FROM missing;", encoding="utf-8")
    assert main([str(script)]) == 1
    assert "Unknown table" in capsys.readouterr().err


def test_main_missing_file(capsys):
    assert main(["/nonexistent/x.sql"]) == 1
    assert "not found" in capsys.readouterr().err.lower()


def test_repl_flow(monkeypatch, capsys):
    inputs = iter([
        "CREATE TABLE t (id INTEGER PRIMARY KEY);",
        "INSERT INTO t VALUES (1);",
        "SELECT *",
        "FROM t;",
        ".tables",
        ".exit",
    ])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    from storelens.cli import Shell
    Shell().repl()
    out = capsys.readouterr().out
    assert "created" in out
    assert "(1 row)" in out
