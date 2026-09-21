import os

import pytest

from kbsearch import KBSearch, SynonymMap


def build_sample(kb):
    kb.add_document(1, "冰箱压缩机异响，需要维修")
    kb.add_document(2, "空调不制冷，冷媒泄漏")
    kb.add_document("manual-a", "Compressor repair manual")


def test_save_load_roundtrip(tmp_path):
    path = str(tmp_path / "idx.json")
    kb = KBSearch()
    build_sample(kb)
    before = kb.search("压缩机", top_k=0)
    kb.save(path)

    kb2 = KBSearch.load(path)
    assert kb2.document_count() == 3
    after = kb2.search("压缩机", top_k=0)
    assert before == after


def test_doc_id_types_preserved(tmp_path):
    path = str(tmp_path / "idx.json")
    kb = KBSearch()
    build_sample(kb)
    kb.save(path)
    kb2 = KBSearch.load(path)
    ids = {h["doc_id"] for h in kb2.search("压缩机 OR 冷媒 OR compressor", top_k=0)}
    assert 1 in ids and isinstance(1, int)
    assert "manual-a" in ids
    # int 1 did not silently become "1"
    kb2.remove_document(1)
    assert kb2.document_count() == 2


def test_snippet_works_after_reload(tmp_path):
    path = str(tmp_path / "idx.json")
    kb = KBSearch()
    build_sample(kb)
    kb.save(path)
    kb2 = KBSearch.load(path)
    hits = kb2.search("不制冷", with_snippet=True)
    assert hits and "不制冷" in hits[0]["snippet"]


def test_stopword_setting_persisted(tmp_path):
    path = str(tmp_path / "idx.json")
    kb = KBSearch(use_stopwords=False)
    kb.add_document(1, "the compressor")
    kb.save(path)
    kb2 = KBSearch.load(path)
    assert kb2.use_stopwords is False
    assert kb2.search("the")


def test_incremental_readd_no_residue(tmp_path):
    path = str(tmp_path / "idx.json")
    kb = KBSearch()
    kb.add_document("doc1", "旧政策 返修 免费更换")
    kb.save(path)

    # simulate the on-disk file changing: reload and re-add only that doc
    kb2 = KBSearch.load(path)
    kb2.add_document("doc1", "新政策 返修 收取工时费")
    kb2.save(path)

    kb3 = KBSearch.load(path)
    assert kb3.search("旧政策") == []          # old term fully gone
    assert kb3.search("免费") == []
    assert {h["doc_id"] for h in kb3.search("新政策")} == {"doc1"}
    assert {h["doc_id"] for h in kb3.search("工时费")} == {"doc1"}
    assert kb3.document_count() == 1


def test_remove_then_save_load(tmp_path):
    path = str(tmp_path / "idx.json")
    kb = KBSearch()
    build_sample(kb)
    kb.remove_document(2)
    kb.save(path)
    kb2 = KBSearch.load(path)
    assert kb2.search("冷媒") == []
    assert kb2.document_count() == 2


def test_index_file_is_json(tmp_path):
    import json

    path = str(tmp_path / "idx.json")
    kb = KBSearch()
    build_sample(kb)
    kb.save(path)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["version"] == 1
    assert "postings" in data and "doc_lengths" in data


def test_load_with_synonyms(tmp_path):
    syn_path = tmp_path / "syn.txt"
    syn_path.write_text("冰箱=冰柜\n", encoding="utf-8")
    path = str(tmp_path / "idx.json")
    kb = KBSearch()
    kb.add_document(1, "冰柜不制冷")
    kb.save(path)
    kb2 = KBSearch.load(path, synonyms=SynonymMap.from_file(str(syn_path)))
    assert {h["doc_id"] for h in kb2.search("冰箱")} == {1}
