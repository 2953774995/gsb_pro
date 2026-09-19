"""TF-IDF scoring: hand-computable corpora with asserted order and values."""

import math

import pytest

from minisearch import SearchEngine


def expected_score(tf, df, n):
    return (1.0 + math.log(tf)) * math.log(1.0 + n / df)


def test_tf_log_normalization_orders_by_frequency():
    e = SearchEngine()
    e.add_document(1, "apple apple apple")
    e.add_document(2, "apple banana")
    results = e.search("apple")
    assert [r.doc_id for r in results] == [1, 2]
    assert results[0].score == pytest.approx(expected_score(tf=3, df=2, n=2))
    assert results[1].score == pytest.approx(expected_score(tf=1, df=2, n=2))


def test_idf_rewards_rare_terms():
    e = SearchEngine()
    e.add_document(1, "common rare")
    e.add_document(2, "common common common")
    results = e.search("common OR rare")
    # doc1: common(1*log2) + rare(1*log3) ~= 1.79 beats doc2: 3x common ~= 1.45
    assert [r.doc_id for r in results] == [1, 2]
    assert results[0].score == pytest.approx(
        expected_score(1, 2, 2) + expected_score(1, 1, 2)
    )
    assert results[1].score == pytest.approx(expected_score(3, 2, 2))


def test_boolean_results_sorted_by_score_descending():
    e = SearchEngine()
    e.add_document(1, "apple")
    e.add_document(2, "apple apple apple")
    e.add_document(3, "apple apple")
    results = e.search("apple OR banana")
    assert [r.doc_id for r in results] == [2, 3, 1]
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_and_sums_component_scores():
    e = SearchEngine()
    e.add_document(1, "apple banana")
    e.add_document(2, "apple apple banana")
    results = e.search("apple AND banana")
    assert [r.doc_id for r in results] == [2, 1]
    assert results[0].score == pytest.approx(
        expected_score(2, 2, 2) + expected_score(1, 2, 2)
    )


def test_idf_smoother_for_universal_term():
    # A term present in every document still gets a positive (small) idf.
    e = SearchEngine()
    e.add_document(1, "everywhere alpha")
    e.add_document(2, "everywhere beta")
    results = e.search("everywhere")
    assert len(results) == 2
    assert all(r.score > 0 for r in results)
