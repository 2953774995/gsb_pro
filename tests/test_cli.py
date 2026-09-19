"""CLI: directory indexing and the interactive loop."""

import pytest

from minisearch.cli import build_engine, main


@pytest.fixture
def docs_dir(tmp_path):
    (tmp_path / "python.txt").write_text(
        "Python Web Notes\npython web server framework\n", encoding="utf-8"
    )
    (tmp_path / "java.txt").write_text(
        "Java Web Notes\njava web server spring\n", encoding="utf-8"
    )
    (tmp_path / "chinese.txt").write_text(
        "中文文档\n搜索引擎 全文检索\n", encoding="utf-8"
    )
    (tmp_path / "ignored.md").write_text("not indexed\n", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "nested.txt").write_text("nested python doc\n", encoding="utf-8")
    return tmp_path


def test_build_engine_indexes_txt_recursively(docs_dir):
    engine, titles = build_engine(docs_dir)
    assert engine.document_count() == 4  # .md ignored, nested .txt included
    assert engine.search("python AND web")[0].doc_id == "python.txt"
    assert engine.search("搜索引擎")[0].doc_id == "chinese.txt"
    # First line used as title.
    assert titles["python.txt"] == "Python Web Notes"
    # Nested files use their relative path as doc_id.
    assert engine.search("nested")[0].doc_id == "sub/nested.txt"


def test_cli_repl_boolean_query(docs_dir, monkeypatch, capsys):
    inputs = iter(["web AND NOT java", "bad AND", ":quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    rc = main([str(docs_dir)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Indexed 4 document(s)" in out
    assert "python.txt" in out
    assert "java.txt" not in out.split("query error")[0].split("Indexed")[1]
    assert "query error:" in out  # invalid query reported, loop survives


def test_cli_rejects_missing_directory(tmp_path, capsys):
    rc = main([str(tmp_path / "nope")])
    assert rc == 2
    assert "not a directory" in capsys.readouterr().err
