import io
import json

from storelens import Engine
from storelens.cli import format_table, main, repl, run_script


def test_format_table_alignment():
    text = format_table(["id", "name"], [(1, "cola"), (20, None)])
    lines = text.split("\n")
    assert lines[0] == "id | name"
    assert set(lines[1]) <= set("-+")
    assert lines[2].startswith("1  | cola")
    assert "NULL" in lines[3]
    assert lines[-1] == "(2 rows)"
    # all data lines have equal visible width
    assert len(lines[2]) == len(lines[3])


def test_run_script_outputs_tables():
    engine = Engine()
    out = io.StringIO()
    ok = run_script(engine, "CREATE TABLE t (a INTEGER); INSERT INTO t VALUES (1);"
                            " SELECT * FROM t;", out)
    assert ok
    text = out.getvalue()
    assert "table t created" in text
    assert "1 row(s) inserted" in text
    assert "a" in text and "1" in text


def test_run_script_reports_error_and_stops():
    engine = Engine()
    out = io.StringIO()
    ok = run_script(engine, "SELECT * FROM missing;", out)
    assert not ok
    assert "Error:" in out.getvalue()


def test_main_with_script_file(tmp_path, capsys):
    script = tmp_path / "script.sql"
    script.write_text("CREATE TABLE t (a INTEGER); INSERT INTO t VALUES (7);"
                      " SELECT a FROM t;", encoding="utf-8")
    assert main([str(script)]) == 0
    out = capsys.readouterr().out
    assert "7" in out


def test_main_missing_file(capsys):
    assert main(["/nonexistent/script.sql"]) == 1
    assert "Error" in capsys.readouterr().err


def test_repl_meta_commands_and_queries(tmp_path):
    data = tmp_path / "rows.json"
    data.write_text(json.dumps([{"id": 1, "name": "cola"}]), encoding="utf-8")
    inp = io.StringIO(
        ".tables\n"
        "CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT);\n"
        ".import products %s\n"
        "SELECT * FROM products;\n"
        ".schema products\n"
        ".tables\n"
        ".bogus\n"
        ".quit\n" % data)
    out = io.StringIO()
    repl(Engine(), inp=inp, out=out)
    text = out.getvalue()
    assert "(no datasets)" in text
    assert "1 row(s) imported into products" in text
    assert "cola" in text
    assert "id INTEGER PRIMARY KEY" in text
    assert "products" in text
    assert "unknown command" in text
