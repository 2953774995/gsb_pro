import time

import pytest

from minisearch import SearchEngine


@pytest.fixture
def big_engine():
    """One ~1MB document plus a few small distractors."""
    eng = SearchEngine()
    sentence = ("the quick brown fox jumps over the lazy dog while "
                "search engines index documents at scale ")
    text = sentence * 12000  # ~1.1 MB
    assert len(text) > 1_000_000
    eng.add_document("big", text)
    eng.add_document("needle", "a rare unicorn appears here")
    for i in range(50):
        eng.add_document("filler-%d" % i, "common filler text " * 20)
    return eng


def test_large_document_term_query(big_engine):
    start = time.perf_counter()
    results = big_engine.search("unicorn")
    elapsed = time.perf_counter() - start
    assert [r["doc_id"] for r in results] == ["needle"]
    assert elapsed < 1.0


def test_large_document_boolean_query(big_engine):
    start = time.perf_counter()
    results = big_engine.search("fox AND NOT unicorn", top_k=0)
    elapsed = time.perf_counter() - start
    assert "big" in [r["doc_id"] for r in results]
    assert "needle" not in [r["doc_id"] for r in results]
    assert elapsed < 1.0


def test_large_document_phrase_query(big_engine):
    start = time.perf_counter()
    results = big_engine.search('"quick brown fox"')
    elapsed = time.perf_counter() - start
    assert [r["doc_id"] for r in results] == ["big"]
    assert elapsed < 2.0


def test_large_document_prefix_query(big_engine):
    start = time.perf_counter()
    results = big_engine.search("unic*")
    elapsed = time.perf_counter() - start
    assert [r["doc_id"] for r in results] == ["needle"]
    assert elapsed < 1.0


def test_add_large_document_performance():
    eng = SearchEngine()
    text = "search engines love indexing documents " * 25000  # ~1MB
    start = time.perf_counter()
    eng.add_document(1, text)
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0
