import math

from kbsearch import KBSearch


def test_tfidf_manual_order_and_top_k():
    kb = KBSearch()
    kb.add_document("a", "alpha alpha alpha beta")
    kb.add_document("b", "alpha gamma")
    kb.add_document("c", "gamma gamma beta")

    results = kb.search("alpha OR beta OR gamma", top_k=0)
    by_id = {r["doc_id"]: r["score"] for r in results}
    n = 3
    idf = lambda df: math.log(1 + n / df)
    expected_a = (1 + math.log(3)) * idf(2) + idf(2)  # alpha + beta
    expected_c = (1 + math.log(2)) * idf(2) + idf(2)  # gamma + beta
    expected_b = idf(2) + idf(2)
    assert by_id["a"] == round(expected_a, 8)
    assert by_id["c"] == round(expected_c, 8)
    assert by_id["b"] == round(expected_b, 8)
    assert [r["doc_id"] for r in results] == ["a", "c", "b"]
    assert len(kb.search("alpha OR beta OR gamma", top_k=2)) == 2


def test_boolean_and_snippet_result():
    kb = KBSearch()
    text = "上门检测发现冰箱压缩机异响，需要检查风扇。" * 2 + "压缩机"
    kb.add_document(1, text)
    result = kb.search("压缩机 AND 异响", top_k=1, with_snippet=True)[0]
    assert result["doc_id"] == 1
    assert result["score"] > 0
    assert len(result["snippet"]) <= 80
    assert "压缩机" in result["snippet"]


def test_not_only_snippet_uses_budget_and_not_excluded_term():
    kb = KBSearch()
    text = "alpha " + "pad " * 30
    kb.add_document("d", text)
    result = kb.search("NOT missing", top_k=1, with_snippet=True)[0]
    assert len(result["snippet"]) <= 80
    assert "missing" not in result["snippet"]
