import time

import pytest

from kbsearch import KBSearch


def test_large_document_1mb():
    kb = KBSearch()
    chunk = "压缩机维修手册章节，包含故障排查流程与 compressor repair steps。"
    text = chunk * (1024 * 1024 // len(chunk.encode("utf-8")) + 1)
    assert len(text.encode("utf-8")) >= 1024 * 1024
    start = time.time()
    kb.add_document("big", text)
    hits = kb.search("压缩机 AND 维修", top_k=5, with_snippet=True)
    elapsed = time.time() - start
    assert [h["doc_id"] for h in hits] == ["big"]
    assert "压缩机" in hits[0]["snippet"]
    assert elapsed < 10  # generous bound; typically < 2s


def test_ten_thousand_documents():
    kb = KBSearch()
    n = 10000
    start = time.time()
    for i in range(n):
        kb.add_document(i, "工单%d 冰箱维修 更换零件 测试完成 %d" % (i, i % 97))
    build = time.time() - start
    assert kb.document_count() == n

    start = time.time()
    hits = kb.search("冰箱 AND 维修", top_k=10)
    query_time = time.time() - start
    assert len(hits) == 10
    assert query_time < 5  # generous bound; typically < 0.5s

    hits_all = kb.search("冰箱", top_k=0)
    assert len(hits_all) == n
    scores = [h["score"] for h in hits_all]
    assert scores == sorted(scores, reverse=True)
    assert build < 60  # generous bound; typically a few seconds
