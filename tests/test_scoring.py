"""TF-IDF 排序正确性（可手算固定语料）与 top_k 截断。"""

import math

import pytest

from minisearch import SearchEngine


@pytest.fixture()
def engine():
    e = SearchEngine()
    e.add_document("d1", "apple apple banana")
    e.add_document("d2", "apple banana")
    e.add_document("d3", "banana")
    return e


def test_tfidf_scores_hand_computed(engine):
    # N=3, df(apple)=2 -> idf=log(1+3/2)=log(2.5)
    idf = math.log(1 + 3 / 2)
    results = engine.search("apple")
    assert [r["doc_id"] for r in results] == ["d1", "d2"]
    assert results[0]["score"] == pytest.approx((1 + math.log10(2)) * idf)
    assert results[1]["score"] == pytest.approx(1.0 * idf)


def test_boolean_results_ranked_by_score(engine):
    # d1: apple(tf=2)+banana, d2: apple+banana, d3: banana
    results = engine.search("apple OR banana")
    assert [r["doc_id"] for r in results] == ["d1", "d2", "d3"]
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_and_score_is_sum(engine):
    idf_apple = math.log(1 + 3 / 2)
    idf_banana = math.log(1 + 3 / 3)
    results = engine.search("apple AND banana")
    assert [r["doc_id"] for r in results] == ["d1", "d2"]
    assert results[0]["score"] == pytest.approx(
        (1 + math.log10(2)) * idf_apple + idf_banana
    )
    assert results[1]["score"] == pytest.approx(idf_apple + idf_banana)


def test_rarer_term_scores_higher():
    e = SearchEngine()
    e.add_document("d1", "common rare")
    e.add_document("d2", "common common")
    e.add_document("d3", "common common")
    results = e.search("rare")
    idf_rare = math.log(1 + 3 / 1)
    assert results[0]["score"] == pytest.approx(idf_rare)
    common_results = e.search("common")
    assert common_results[0]["score"] < results[0]["score"]


def test_top_k_truncation(engine):
    results = engine.search("apple OR banana", top_k=2)
    assert len(results) == 2
    assert [r["doc_id"] for r in results] == ["d1", "d2"]


def test_top_k_zero_returns_all(engine):
    results = engine.search("apple OR banana", top_k=0)
    assert len(results) == 3


def test_top_k_default_is_10():
    e = SearchEngine()
    for i in range(20):
        e.add_document("doc%d" % i, "shared term %d" % i)
    assert len(e.search("shared")) == 10
    assert len(e.search("shared", top_k=0)) == 20


def test_scores_descending_with_many_docs():
    e = SearchEngine()
    for i in range(15):
        e.add_document("doc%d" % i, "word " * (i + 1))
    results = e.search("word", top_k=0)
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)
