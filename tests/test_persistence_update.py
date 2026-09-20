from pathlib import Path

from kbsearch import KBSearch


def test_save_load_and_incremental_file_update(tmp_path):
    corpus = tmp_path / "docs"
    corpus.mkdir()
    one = corpus / "one.txt"
    two = corpus / "two.txt"
    one.write_text("旧故障 compressor oldnoise\n旧词内容", encoding="utf-8")
    two.write_text("其他手册 fan motor", encoding="utf-8")

    index_path = tmp_path / "index.json"
    kb = KBSearch()
    stats = kb.index_directory(str(corpus))
    assert stats["files"] == 2
    kb.save(str(index_path))

    reloaded = KBSearch.load(str(index_path))
    assert reloaded.document_count() == 2
    assert reloaded.search("旧故障", top_k=0)[0]["doc_id"] == "one.txt"

    one.write_text("新故障 evaporator newnoise\n新词内容", encoding="utf-8")
    assert reloaded.update_file(str(one)) is True
    reloaded.save(str(index_path))
    final = KBSearch.load(str(index_path))
    assert final.document_count() == 2
    assert final.search("旧故障", top_k=0) == []
    assert final.search("旧词", top_k=0) == []
    assert final.search("新故障", top_k=0)[0]["doc_id"] == "one.txt"
    assert final.search("evaporator", top_k=0)[0]["doc_id"] == "one.txt"
    # The untouched document's postings remain queryable.
    assert final.search("motor", top_k=0)[0]["doc_id"] == "two.txt"


def test_reindex_detects_all_files_and_id_types_survive(tmp_path):
    kb = KBSearch()
    kb.add_document(7, "integer doc")
    kb.add_document("seven", "string doc")
    path = tmp_path / "idx.json"
    kb.save(str(path))
    loaded = KBSearch.load(str(path))
    assert {r["doc_id"] for r in loaded.search("doc", top_k=0)} == {7, "seven"}
    assert isinstance(loaded.search("integer", top_k=0)[0]["doc_id"], int)


def test_update_unknown_relative_file_is_added_once(tmp_path):
    docs = tmp_path / "manuals"
    docs.mkdir()
    new_file = docs / "new.txt"
    new_file.write_text("新到手册 compressor", encoding="utf-8")

    kb = KBSearch()
    assert kb.update_file(str(new_file), force=True) is True
    # Repeating the update must replace, not create a second document.
    assert kb.update_file(str(new_file), force=True) is True
    assert kb.document_count() == 1
    assert kb.search("新到", top_k=0)[0]["doc_id"] == "new.txt"


def test_directory_scan_skips_synonyms_config(tmp_path):
    docs = tmp_path / "manuals"
    docs.mkdir()
    (docs / "one.txt").write_text("冰箱手册", encoding="utf-8")
    (docs / "synonyms.txt").write_text("冰箱=冰柜\n", encoding="utf-8")
    kb = KBSearch()
    stats = kb.index_directory(str(docs))
    assert stats["files"] == 1
    assert kb.document_count() == 1


def test_reindex_removes_deleted_file_postings(tmp_path):
    docs = tmp_path / "manuals"
    docs.mkdir()
    stale = docs / "stale.txt"
    keep = docs / "keep.txt"
    stale.write_text("旧压缩机手册", encoding="utf-8")
    keep.write_text("风扇手册", encoding="utf-8")
    kb = KBSearch()
    kb.index_directory(str(docs))
    assert kb.document_count() == 2

    stale.unlink()
    kb.index_directory(str(docs), reindex=True)
    assert kb.document_count() == 1
    assert kb.search("旧", top_k=0) == []
    assert kb.search("风扇", top_k=0)[0]["doc_id"] == "keep.txt"


def test_update_file_accepts_relative_id_from_directory(tmp_path):
    docs = tmp_path / "manuals"
    nested = docs / "team-a"
    nested.mkdir(parents=True)
    path = nested / "ticket.txt"
    path.write_text("旧内容 compressor", encoding="utf-8")
    kb = KBSearch()
    kb.index_directory(str(docs))
    assert kb.document_count() == 1

    path.write_text("新内容 evaporator", encoding="utf-8")
    changed = kb.update_file("team-a/ticket.txt")
    assert changed is True
    assert kb.document_count() == 1
    assert kb.search("旧", top_k=0) == []
    assert kb.search("evaporator", top_k=0)[0]["doc_id"] == "team-a/ticket.txt"


def test_stopword_settings_and_positions_round_trip(tmp_path):
    path = tmp_path / "idx.json"
    kb = KBSearch()
    kb.add_document("a", "the fan does not cool")
    kb.save(str(path))
    loaded = KBSearch.load(str(path))
    assert loaded.index.analyzer.use_stopwords is True
    assert loaded.index.document_frequency("the") == 0
    assert loaded.index.doc_stop_positions["a"]["the"] == [0]
    assert [r["doc_id"] for r in loaded.search('"does not cool"', top_k=0)] == ["a"]

    kb2 = KBSearch(use_stopwords=False)
    kb2.add_document("b", "the fan")
    kb2.save(str(path))
    loaded2 = KBSearch.load(str(path))
    assert loaded2.index.analyzer.use_stopwords is False
    assert loaded2.search("the", top_k=0)[0]["doc_id"] == "b"
