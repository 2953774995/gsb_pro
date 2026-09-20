"""索引正确性：词频/df/重复添加覆盖/删除清理。"""

from minisearch import SearchEngine
from minisearch.index import InvertedIndex
from minisearch.tokenizer import tokenize


def make_index():
    return InvertedIndex()


def test_tf_and_positions():
    idx = make_index()
    idx.add_document("d1", tokenize("apple apple banana"), "apple apple banana")
    posting = idx.postings["apple"]["d1"]
    assert posting["tf"] == 2
    assert posting["positions"] == [0, 1]
    assert idx.postings["banana"]["d1"]["tf"] == 1


def test_df_and_doc_length():
    idx = make_index()
    idx.add_document("d1", tokenize("apple banana"), "apple banana")
    idx.add_document("d2", tokenize("apple cherry"), "apple cherry")
    assert idx.df("apple") == 2
    assert idx.df("banana") == 1
    assert idx.df("missing") == 0
    assert idx.doc_lengths["d1"] == 2
    assert idx.num_docs == 2


def test_duplicate_add_overwrites():
    idx = make_index()
    idx.add_document("d1", tokenize("apple apple"), "apple apple")
    idx.add_document("d1", tokenize("banana"), "banana")
    assert idx.num_docs == 1
    assert "apple" not in idx.postings  # 旧 term 无残留
    assert idx.df("banana") == 1
    assert idx.doc_lengths["d1"] == 1


def test_remove_cleans_all_state():
    idx = make_index()
    idx.add_document("d1", tokenize("apple banana"), "apple banana")
    idx.add_document("d2", tokenize("apple cherry"), "apple cherry")
    assert idx.remove_document("d1") is True
    assert idx.df("apple") == 1
    assert "banana" not in idx.postings  # 只出现在 d1 的 term 整体清除
    assert "d1" not in idx.doc_lengths
    assert "d1" not in idx.doc_terms
    assert "d1" not in idx.documents
    assert idx.num_docs == 1


def test_remove_missing_returns_false():
    idx = make_index()
    assert idx.remove_document("nope") is False


def test_engine_document_count_and_overwrite():
    engine = SearchEngine()
    engine.add_document("a", "hello world")
    engine.add_document("b", "hello python")
    assert engine.document_count() == 2
    engine.add_document("a", "totally different")
    assert engine.document_count() == 2
    assert engine.search("hello") == [] or all(
        r["doc_id"] != "a" for r in engine.search("hello")
    )
