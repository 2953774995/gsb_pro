"""Performance smoke tests: 1MB-scale documents and many-document corpora."""

import time

from minisearch import SearchEngine


def test_one_megabyte_document():
    chunk = "alpha beta gamma delta epsilon zeta eta theta "  # 46 chars
    repeats = (1024 * 1024) // len(chunk) + 1
    big_text = chunk * repeats
    assert len(big_text) >= 1024 * 1024

    engine = SearchEngine()
    start = time.perf_counter()
    engine.add_document(1, big_text)
    build_seconds = time.perf_counter() - start

    start = time.perf_counter()
    results = engine.search("alpha AND theta")
    query_seconds = time.perf_counter() - start

    assert [r.doc_id for r in results] == [1]
    assert results[0].score > 0
    assert build_seconds < 10.0, "indexing 1MB regressed: %.2fs" % build_seconds
    assert query_seconds < 2.0, "query on 1MB doc regressed: %.2fs" % query_seconds


def test_many_documents_top_k_stays_fast():
    engine = SearchEngine()
    for i in range(2000):
        engine.add_document(i, "document number %d about topic%d" % (i, i % 10))

    start = time.perf_counter()
    results = engine.search("topic3", top_k=10)
    elapsed = time.perf_counter() - start

    assert len(results) == 10
    assert len(engine.search("topic3", top_k=0)) == 200
    assert elapsed < 2.0


def test_repeated_add_remove_cycles_leave_no_residue():
    engine = SearchEngine()
    for cycle in range(50):
        engine.add_document(1, "ephemeral content %d" % cycle)
        engine.remove_document(1)
    assert engine.document_count() == 0
    assert engine.search("ephemeral") == []
