"""文档管理、中文查询、摘要、删除同步、空索引/无命中、大文档性能。"""

import time

import pytest

from minisearch import SearchEngine, SearchError


def test_doc_id_int_and_str():
    e = SearchEngine()
    e.add_document(1, "hello world")
    e.add_document("two", "hello python")
    results = e.search("hello", top_k=0)
    assert {r["doc_id"] for r in results} == {1, "two"}


def test_invalid_doc_id():
    e = SearchEngine()
    with pytest.raises(TypeError):
        e.add_document(1.5, "text")
    with pytest.raises(ValueError):
        e.add_document("", "text")


def test_case_insensitive_index_and_query():
    e = SearchEngine()
    e.add_document("d", "Hello WORLD")
    assert len(e.search("HELLO")) == 1
    assert len(e.search("world")) == 1
    assert len(e.search("World")) == 1


def test_chinese_query_hits():
    e = SearchEngine()
    e.add_document("cn1", "我爱北京天安门")
    e.add_document("cn2", "上海东方明珠")
    assert [r["doc_id"] for r in e.search("北京")] == ["cn1"]
    assert [r["doc_id"] for r in e.search("天安门")] == ["cn1"]
    assert [r["doc_id"] for r in e.search("京")] == ["cn1"]
    assert e.search("广州") == []


def test_mixed_chinese_english():
    e = SearchEngine()
    e.add_document("mix", "我用Python写代码")
    assert len(e.search("python")) == 1
    assert len(e.search("代码")) == 1
    assert len(e.search("Python 代码")) == 1


def test_empty_index_returns_empty():
    e = SearchEngine()
    assert e.search("anything") == []
    assert e.search("anything", with_snippet=True) == []


def test_no_hit_returns_empty():
    e = SearchEngine()
    e.add_document("d", "some content")
    assert e.search("nonexistent") == []


def test_empty_query_raises():
    e = SearchEngine()
    with pytest.raises(SearchError):
        e.search("")
    with pytest.raises(SearchError):
        e.search("   ")


def test_remove_syncs_query_results():
    e = SearchEngine()
    e.add_document("d1", "apple banana")
    e.add_document("d2", "apple cherry")
    assert len(e.search("banana")) == 1
    assert e.remove_document("d1") is True
    assert e.search("banana") == []          # 删除后无残留
    assert len(e.search("apple")) == 1
    assert e.document_count() == 1
    assert e.remove_document("d2") is True
    assert e.search("apple") == []
    assert e.document_count() == 0


def test_remove_missing_document():
    e = SearchEngine()
    assert e.remove_document("ghost") is False


def test_duplicate_add_overwrites_old_terms():
    e = SearchEngine()
    e.add_document("d", "oldterm unique_old")
    e.add_document("d", "newterm unique_new")
    assert e.search("oldterm") == []
    assert e.search("unique_old") == []
    assert len(e.search("newterm")) == 1


def test_result_fields():
    e = SearchEngine()
    e.add_document("d", "hello world")
    (r,) = e.search("hello")
    assert r["doc_id"] == "d"
    assert isinstance(r["score"], float)
    assert "snippet" not in r
    (r,) = e.search("hello", with_snippet=True)
    assert "hello" in r["snippet"].lower()


def test_snippet_window_around_hit():
    e = SearchEngine()
    text = "padding " * 40 + "targetword " + "tail " * 40
    e.add_document("d", text)
    (r,) = e.search("targetword", with_snippet=True)
    snippet = r["snippet"]
    assert "targetword" in snippet
    # 窗口共 80 字符，两侧可能有 ... 省略号
    assert len(snippet) <= 80 + 6
    assert snippet.startswith("...")
    assert snippet.endswith("...")


def test_snippet_chinese_hit():
    e = SearchEngine()
    e.add_document("cn", "春眠不觉晓处处闻啼鸟夜来风雨声花落知多少")
    (r,) = e.search("风雨", with_snippet=True)
    assert "风" in r["snippet"]


def test_stopwords_toggle():
    e = SearchEngine()
    e.add_document("d", "the end")
    assert e.search("the") == [] or all(
        r["score"] == 0 for r in e.search("the")
    )
    e2 = SearchEngine(use_stopwords=False)
    e2.add_document("d", "the end")
    assert len(e2.search("the")) == 1


def test_negative_top_k_raises():
    e = SearchEngine()
    with pytest.raises(SearchError):
        e.search("x", top_k=-1)


def test_large_document_performance():
    """1MB 级大文档：建索引与查询性能不退化。"""
    base = (
        "lorem ipsum dolor sit amet consectetur adipiscing elit "
        "sed do eiusmod tempor incididunt ut labore et dolore magna aliqua "
    )
    # 构造 >= 1MB 文本，并混入少量变化避免完全重复
    repeats = (1024 * 1024) // len(base) + 1
    text = " ".join(
        "%s variant%d" % (base.strip(), i % 100) for i in range(repeats)
    )
    assert len(text) >= 1024 * 1024

    e = SearchEngine()
    start = time.perf_counter()
    e.add_document("big", text)
    for i in range(20):
        e.add_document("small%d" % i, "lorem small document %d" % i)
    index_time = time.perf_counter() - start
    assert index_time < 10.0, "建索引过慢: %.2fs" % index_time

    start = time.perf_counter()
    for _ in range(100):
        results = e.search("lorem AND variant7", top_k=5)
    query_time = time.perf_counter() - start
    assert query_time < 2.0, "查询过慢: %.2fs" % query_time
    assert results and results[0]["doc_id"] == "big"
    assert len(e.search('"dolore magna"')) >= 1
