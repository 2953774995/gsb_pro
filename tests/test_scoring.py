import math

import pytest

from kbsearch import KBSearch


def idf(n, df):
    return math.log(1 + n / df)


def tfw(tf):
    return 1 + math.log(tf)


@pytest.fixture()
def corpus():
    kb = KBSearch()
    kb.add_document("d1", "apple apple apple")
    kb.add_document("d2", "apple banana")
    kb.add_document("d3", "banana")
    return kb


def test_tfidf_exact_scores(corpus):
    res = {h["doc_id"]: h["score"] for h in corpus.search("apple")}
    assert set(res) == {"d1", "d2"}
    assert res["d1"] == pytest.approx(tfw(3) * idf(3, 2))
    assert res["d2"] == pytest.approx(tfw(1) * idf(3, 2))


def test_tfidf_ranking_order(corpus):
    # hand-computable: d1 (tf=3) > d2 (tf=1) for 'apple'
    hits = corpus.search("apple")
    assert [h["doc_id"] for h in hits] == ["d1", "d2"]


def test_rarer_term_scores_higher(corpus):
    # 'cherry' appears in 1 doc, 'apple' in 2 of 3 -> higher idf
    corpus.add_document("d4", "cherry")
    rare = corpus.search("cherry")[0]["score"]
    common = corpus.search("apple")[0]["score"]  # even with tf=3
    assert rare == pytest.approx(tfw(1) * idf(4, 1))
    assert idf(4, 1) > idf(4, 2)


def test_boolean_results_are_ranked(corpus):
    hits = corpus.search("apple OR banana")
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)
    # d1: tf(apple)=3 -> tfw(3)*idf; d2: both terms -> 2*tfw(1)*idf; d3: one term
    assert [h["doc_id"] for h in hits] == ["d1", "d2", "d3"]
    assert hits[0]["score"] == pytest.approx(tfw(3) * idf(3, 2))
    assert hits[1]["score"] == pytest.approx(2 * tfw(1) * idf(3, 2))
    assert hits[2]["score"] == pytest.approx(tfw(1) * idf(3, 2))


def test_and_sums_scores(corpus):
    res = {h["doc_id"]: h["score"] for h in corpus.search("apple AND banana")}
    assert set(res) == {"d2"}
    assert res["d2"] == pytest.approx(2 * tfw(1) * idf(3, 2))


def test_top_k_truncation():
    kb = KBSearch()
    for i in range(8):
        kb.add_document(i, "common term " + "x%d" % i)
    assert len(kb.search("common", top_k=3)) == 3
    assert len(kb.search("common")) == 8           # default 10 > 8
    assert len(kb.search("common", top_k=0)) == 8  # 0 means all
    assert len(kb.search("common", top_k=100)) == 8


def test_top_k_keeps_best():
    kb = KBSearch()
    kb.add_document("best", "term term term term")
    kb.add_document("mid", "term term")
    kb.add_document("low", "term")
    hits = kb.search("term", top_k=2)
    assert [h["doc_id"] for h in hits] == ["best", "mid"]
