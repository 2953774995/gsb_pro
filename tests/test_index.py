import pytest

from kbsearch import KBSearch


def test_add_repeat_overwrite_and_counts():
    kb = KBSearch()
    kb.add_document(1, "压缩机 异响 compressor noise")
    assert kb.document_count() == 1
    assert kb.index.term_frequency("压", 1) == 1
    kb.add_document(1, "冰箱 不制冷 fridge cool")
    assert kb.document_count() == 1
    assert kb.index.term_frequency("压", 1) == 0
    assert kb.index.term_frequency("冰", 1) == 1
    assert kb.index.doc_lengths[1] == 7


def test_int_and_str_doc_ids_are_distinct():
    kb = KBSearch()
    kb.add_document(1, "alpha")
    kb.add_document("1", "beta")
    assert kb.document_count() == 2
    assert [r["doc_id"] for r in kb.search("alpha OR beta", top_k=0)] == [1, "1"]


def test_remove_cleans_all_postings_and_stats():
    kb = KBSearch()
    kb.add_document("a", "old compressor old")
    kb.add_document("b", "compressor")
    assert kb.remove_document("a") is True
    assert kb.index.document_frequency("old") == 0
    assert "old" not in index_terms(kb)
    assert kb.index.doc_lengths.get("a") is None
    assert kb.search("old", top_k=0) == []
    assert [r["doc_id"] for r in kb.search("compressor", top_k=0)] == ["b"]
    with pytest.raises(TypeError):
        kb.add_document([1], "bad id")


def test_term_frequency_and_positions():
    kb = KBSearch()
    kb.add_document("d", "noise noise noise 异响")
    assert kb.index.term_frequency("noise", "d") == 3
    assert kb.index.positions("noise", "d") == (0, 1, 2)
    assert kb.index.positions("异", "d") == (3,)


def index_terms(kb):
    return list(kb.index.postings)
