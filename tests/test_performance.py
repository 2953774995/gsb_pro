import time

from kbsearch import KBSearch


def test_large_one_megabyte_document():
    kb = KBSearch()
    text = ("compressor refrigerator repair 压缩机异响 " * 25000)
    assert len(text.encode("utf-8")) > 1024 * 1024
    kb.add_document("large", text)
    start = time.perf_counter()
    results = kb.search("压缩机 AND 异响", top_k=10)
    assert time.perf_counter() - start < 1.0
    assert results[0]["doc_id"] == "large"


def test_ten_thousand_documents_search_scale():
    kb = KBSearch()
    words = ["compressor", "fan", "motor", "sensor", "valve", "pump"]
    for i in range(10000):
        word = words[i % len(words)]
        kb.add_document(i, "doc %d %s repair 冰箱 维修" % (i, word))
    start = time.perf_counter()
    results = kb.search("compressor AND (repair OR 维修)", top_k=10)
    assert time.perf_counter() - start < 2.0
    assert len(results) == 10
    assert all(r["doc_id"] % len(words) == 0 for r in results)
