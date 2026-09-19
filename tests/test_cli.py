import io

import pytest

from minisearch.cli import build_engine_from_dir, main, repl, run_query


@pytest.fixture
def corpus_dir(tmp_path):
    (tmp_path / "python.txt").write_text(
        "Python Guide\npython is a great language for web servers\n",
        encoding="utf-8")
    (tmp_path / "java.txt").write_text(
        "Java Notes\njava runs on the jvm and powers servers\n",
        encoding="utf-8")
    (tmp_path / "chinese.txt").write_text(
        "中文文档\n全文搜索引擎的实现细节\n", encoding="utf-8")
    (tmp_path / "ignore.md").write_text("not indexed", encoding="utf-8")
    return str(tmp_path)


def ids(results):
    return {hit["doc_id"] for hit in results}


def test_build_engine_from_dir(corpus_dir):
    engine = build_engine_from_dir(corpus_dir)
    assert engine.document_count() == 3  # .md file ignored
    assert ids(run_query(engine, "python")) == {"python.txt"}
    assert ids(run_query(engine, "搜索引擎")) == {"chinese.txt"}


def test_boolean_query_via_cli(corpus_dir):
    engine = build_engine_from_dir(corpus_dir)
    results = run_query(engine, "python OR java AND NOT jvm")
    assert ids(results) == {"python.txt"}
    scores = [hit["score"] for hit in results]
    assert scores == sorted(scores, reverse=True)


def test_repl_query_and_remove(corpus_dir):
    engine = build_engine_from_dir(corpus_dir)
    commands = iter(["python", ":remove python.txt", "python", ":count", ":quit"])
    out = io.StringIO()
    repl(engine, input_fn=lambda prompt: next(commands), out=out)
    text = out.getvalue()
    assert "Indexed 3 documents" in text
    assert text.index("python.txt") < text.index("removed")  # hit before removal
    assert "removed 'python.txt'" in text
    assert "(no hits)" in text                               # gone after removal
    assert "2 documents" in text                             # count after removal


def test_repl_handles_bad_query(corpus_dir):
    engine = build_engine_from_dir(corpus_dir)
    commands = iter(["python AND", ":quit"])
    out = io.StringIO()
    repl(engine, input_fn=lambda prompt: next(commands), out=out)
    assert "query error" in out.getvalue()


def test_main_end_to_end(corpus_dir, monkeypatch, capsys):
    def fake_input(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)
    assert main([corpus_dir]) == 0
    assert "Indexed 3 documents" in capsys.readouterr().out
