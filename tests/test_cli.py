"""CLI：从目录批量建索引、标题提取、交互式查询。"""

from minisearch.cli import build_index, main


def make_docs(tmp_path):
    (tmp_path / "doc1.txt").write_text(
        "Python Web 指南\npython web server programming\n", encoding="utf-8"
    )
    (tmp_path / "doc2.txt").write_text(
        "Java 入门\njava server programming\n", encoding="utf-8"
    )
    (tmp_path / "doc3.txt").write_text("中文文档\n我爱北京天安门\n", encoding="utf-8")
    (tmp_path / "ignore.md").write_text("not indexed\n", encoding="utf-8")
    return tmp_path


def test_build_index_scans_txt_only(tmp_path):
    make_docs(tmp_path)
    engine, titles = build_index(str(tmp_path))
    assert engine.document_count() == 3
    assert titles["doc1"] == "Python Web 指南"
    assert titles["doc3"] == "中文文档"


def test_build_index_boolean_query(tmp_path):
    make_docs(tmp_path)
    engine, _ = build_index(str(tmp_path))
    results = engine.search("server AND NOT java")
    assert [r["doc_id"] for r in results] == ["doc1"]
    results = engine.search("python OR java")
    assert {r["doc_id"] for r in results} == {"doc1", "doc2"}
    # 按分数降序
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_build_index_chinese_hit(tmp_path):
    make_docs(tmp_path)
    engine, _ = build_index(str(tmp_path))
    assert [r["doc_id"] for r in engine.search("北京")] == ["doc3"]


def test_main_repl(tmp_path, monkeypatch, capsys):
    make_docs(tmp_path)
    inputs = iter(["server AND NOT java", "北京", ":count", ":remove doc1", ":count", ":quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    assert main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "doc1" in out
    assert "doc3" in out
    assert "已删除" in out


def test_main_missing_directory(capsys):
    assert main(["/nonexistent-dir-xyz"]) == 2
