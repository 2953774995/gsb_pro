import io

import pytest

from sqlq import Engine
from sqlq.cli import format_value, main, render_table, run_repl, run_script


def test_render_table_aligns_columns():
    text = render_table(["id", "name"], [(1, "ann"), (200, "b")])
    lines = text.splitlines()
    assert lines[1] == "| id  | name |"
    assert lines[3] == "| 1   | ann  |"
    assert lines[4] == "| 200 | b    |"


def test_format_value_rules():
    assert format_value(None) == "NULL"
    assert format_value(1) == "1"
    assert format_value(1.5) == "1.5"
    assert format_value("a b") == "a b"


def test_run_script_prints_tags():
    out = io.StringIO()
    engine = Engine()
    run_script(engine,
               "CREATE TABLE t (a INTEGER); INSERT INTO t VALUES (1);"
               "SELECT * FROM t;", out)
    text = out.getvalue()
    assert "CREATE TABLE OK" in text
    assert "1 row(s) inserted" in text
    assert "| a |" in text and "| 1 |" in text
    assert "1 row(s)" in text


def test_repl_multiline_statement_and_error_recovery():
    in_stream = io.StringIO(
        "CREATE TABLE t (a INTEGER);\nSELECT *\nFROM t;\n"
        "SELECT FROM;\nSELECT 1;\n.exit\n")
    out = io.StringIO()
    run_repl(Engine(), in_stream, out)
    text = out.getvalue()
    assert "| a |" in text          # multiline statement executed
    assert "Error:" in text        # broken statement reported
    assert text.count("1 row(s)") >= 1  # shell keeps running afterwards


def test_repl_meta_commands():
    in_stream = io.StringIO(
        "CREATE TABLE t (a INTEGER PRIMARY KEY, b TEXT);\n"
        ".tables\n.schema\n.exit\n")
    out = io.StringIO()
    run_repl(Engine(), in_stream, out)
    text = out.getvalue()
    assert "t" in text
    assert "CREATE TABLE t (a INTEGER PRIMARY KEY, b TEXT);" in text


def test_main_runs_piped_script(monkeypatch, capsys, tmp_path):
    script = tmp_path / "q.sql"
    script.write_text(
        "CREATE TABLE t (a INTEGER); INSERT INTO t VALUES (2);"
        "SELECT a FROM t;")

    class FakeStdin:
        @staticmethod
        def isatty():
            return False

        @staticmethod
        def read():
            return ""

    monkeypatch.setattr("sys.stdin", FakeStdin)
    assert main([str(script)]) == 0
    captured = capsys.readouterr()
    assert "| 2 |" in captured.out


def test_main_missing_file_returns_nonzero(capsys):
    assert main(["/no/such/file.sql"]) == 1
    assert "Error" in capsys.readouterr().err


def test_main_piped_sql_via_stdin(monkeypatch, capsys):
    fake_stdin = io.StringIO("SELECT 1 + 1;")
    fake_stdin.isatty = lambda: False
    monkeypatch.setattr("sys.stdin", fake_stdin)
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "1 + 1" in output and "| 2     |" in output


def test_main_piped_invalid_sql_exit_code(monkeypatch, capsys):
    fake_stdin = io.StringIO("NOT SQL AT ALL")
    fake_stdin.isatty = lambda: False
    monkeypatch.setattr("sys.stdin", fake_stdin)
    assert main([]) == 1
    assert "Error" in capsys.readouterr().err


def test_east_asian_width_padding():
    text = render_table(["名前"], [("日本語",), ("x",)])
    lines = text.splitlines()
    from sqlq.cli import display_width
    # All rows have equal display width despite different character counts.
    widths = {display_width(line) for line in lines}
    assert len(widths) == 1
    assert "日本語" in lines[3]
