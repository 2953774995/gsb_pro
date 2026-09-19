import io

import pytest

from sqlq.cli import render_table, run_repl, run_script_file
from sqlq.engine import Engine


def test_render_table_aligns_columns():
    text = render_table(["id", "name"], [(1, "alice"), (20, "bob")])
    lines = text.splitlines()
    assert lines[1].startswith("| id")
    assert "alice" in lines[3]
    # Every line shares the same width.
    width = len(lines[0])
    assert all(len(line) == width for line in lines)


def test_render_table_shows_null():
    text = render_table(["v"], [(None,)])
    assert "NULL" in text


def test_repl_executes_statements_and_handles_errors(capsys):
    stream = io.StringIO(
        "CREATE TABLE t (a INTEGER PRIMARY KEY);\n"
        "INSERT INTO t VALUES (1);\n"
        "INSERT INTO t VALUES (1);\n"
        "SELECT * FROM t;\n"
        ".exit\n"
    )
    out = io.StringIO()
    code = run_repl(Engine(), stream, out)
    assert code == 0
    output = out.getvalue()
    assert "CREATE TABLE t" in output
    assert "Error: primary key" in output
    assert "| a |" in output


def test_repl_meta_commands(capsys):
    stream = io.StringIO(".help\n.tables\n.exit\n")
    out = io.StringIO()
    run_repl(Engine(), stream, out)
    output = out.getvalue()
    assert ".tables" in output
    assert "(no tables)" in output


def test_run_script_file(tmp_path):
    path = tmp_path / "script.sql"
    path.write_text(
        "CREATE TABLE t (a INTEGER); INSERT INTO t VALUES (2);"
        "SELECT a FROM t;"
    )
    out = io.StringIO()
    count = run_script_file(Engine(), str(path), out)
    assert count == 3
    assert "2" in out.getvalue()


def test_run_script_from_stdin(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("SELECT 1 + 1;"))
    out = io.StringIO()
    count = run_script_file(Engine(), "-", out)
    assert count == 1
    assert "2" in out.getvalue()
