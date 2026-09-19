import math
import time

import pytest

from minisearch import SearchEngine, SearchError


def ids(results):
    return {hit["doc_id"] for hit in results}


# --------------------------------------------------------------------- #
# TF-IDF scoring
# --------------------------------------------------------------------- #

def test_tfidf_hand_computed_order_and_values():
    eng = SearchEngine()
    eng.add_document(1, "apple apple apple")
    eng.add_document(2, "apple banana")
    eng.add_document(3, "banana banana banana")

    results = eng.search("apple")
    assert [hit["doc_id"] for hit in results] == [1, 2]

    idf = math.log(1 + 3 / 2)  # N=3, df=2
    assert results[0]["score"] == pytest.approx((1 + math.log(3)) * idf)
    assert results[1]["score"] == pytest.approx(1.0 * idf)


def test_rarer_term_scores_higher():
    eng = SearchEngine()
    eng.add_document(1, "common rare")
    eng.add_document(2, "common")
    eng.add_document(3, "common")
    rare_hit = eng.search("rare")[0]
    common_hit = eng.search("common", top_k=0)[0]
    assert rare_hit["score"] > common_hit["score"]


def test_higher_tf_ranks_first():
    eng = SearchEngine()
    eng.add_document("a", "search search search engine")
    eng.add_document("b", "search engine")
    results = eng.search("search")
    assert [hit["doc_id"] for hit in results] == ["a", "b"]
    assert results[0]["score"] > results[1]["score"]


# --------------------------------------------------------------------- #
# top_k
# --------------------------------------------------------------------- #

def test_top_k_truncation():
    eng = SearchEngine()
    for i in range(20):
        eng.add_document(i, "common term")
    assert len(eng.search("common")) == 10          # default top_k=10
    assert len(eng.search("common", top_k=5)) == 5
    assert len(eng.search("common", top_k=0)) == 20  # 0 means all
    assert len(eng.search("common", top_k=100)) == 20


def test_negative_top_k_rejected():
    eng = SearchEngine()
    eng.add_document(1, "x")
    with pytest.raises(SearchError):
        eng.search("x", top_k=-1)


# --------------------------------------------------------------------- #
# edge cases
# --------------------------------------------------------------------- #

def test_empty_index_returns_empty_list():
    eng = SearchEngine()
    assert eng.search("anything") == []
    assert eng.search("a AND b") == []


def test_no_match_returns_empty_list():
    eng = SearchEngine()
    eng.add_document(1, "hello world")
    assert eng.search("missing") == []
    assert eng.search("hello AND missing") == []


def test_empty_query_raises():
    eng = SearchEngine()
    with pytest.raises(SearchError):
        eng.search("")
    with pytest.raises(SearchError):
        eng.search("   ")


def test_case_insensitive_search():
    eng = SearchEngine()
    eng.add_document(1, "PyThOn Is GrEaT")
    assert ids(eng.search("python")) == {1}
    assert ids(eng.search("PYTHON")) == {1}


def test_chinese_query_hits():
    eng = SearchEngine()
    eng.add_document(1, "我喜欢用 Python 写搜索引擎")
    eng.add_document(2, "unrelated english text")
    assert ids(eng.search("搜索引擎")) == {1}
    assert ids(eng.search("搜索")) == {1}
    assert ids(eng.search("擎")) == {1}
    assert ids(eng.search("python AND 搜索")) == {1}


def test_remove_document_updates_results():
    eng = SearchEngine()
    eng.add_document(1, "apple banana")
    eng.add_document(2, "apple cherry")
    assert ids(eng.search("banana")) == {1}
    eng.remove_document(1)
    assert eng.document_count() == 1
    assert eng.search("banana") == []
    assert ids(eng.search("apple")) == {2}
    # re-adding after removal works
    eng.add_document(1, "banana again")
    assert ids(eng.search("banana")) == {1}


def test_readd_same_id_overwrites():
    eng = SearchEngine()
    eng.add_document(1, "old content here")
    eng.add_document(1, "new content here")
    assert eng.document_count() == 1
    assert eng.search("old") == []
    assert ids(eng.search("new")) == {1}


def test_int_and_str_doc_ids_mixed():
    eng = SearchEngine()
    eng.add_document(1, "mixed id corpus")
    eng.add_document("doc-2", "mixed id corpus")
    assert ids(eng.search("mixed")) == {1, "doc-2"}


def test_invalid_doc_id_type():
    eng = SearchEngine()
    with pytest.raises(TypeError):
        eng.add_document(1.5, "text")
    with pytest.raises(TypeError):
        eng.add_document(None, "text")


def test_result_structure_and_snippet():
    eng = SearchEngine()
    text = "alpha " * 30 + "needle target" + " omega" * 30
    eng.add_document(1, text)
    results = eng.search("needle", with_snippet=True)
    hit = results[0]
    assert hit["doc_id"] == 1
    assert hit["score"] > 0
    snippet = hit["snippet"]
    assert "needle" in snippet
    assert len(snippet) <= 80 + 6  # 80 chars + two '...' markers
    assert snippet.startswith("...")
    # without snippet flag there is no snippet key
    assert "snippet" not in eng.search("needle")[0]


def test_snippet_short_text_returned_whole():
    eng = SearchEngine()
    eng.add_document(1, "short text")
    assert eng.search("short", with_snippet=True)[0]["snippet"] == "short text"


# --------------------------------------------------------------------- #
# performance: ~1MB document
# --------------------------------------------------------------------- #

def test_large_document_performance():
    eng = SearchEngine()
    words = ("lorem ipsum dolor sit amet consectetur adipiscing elit "
             "sed do eiusmod tempor incididunt ut labore et dolore "
             "magna aliqua needle haystack ").split()
    repeats = (1024 * 1024) // 60
    big_text = " ".join(words * repeats)
    assert len(big_text) >= 1024 * 1024  # ~1MB

    start = time.monotonic()
    eng.add_document("big", big_text)
    for i in range(10):
        eng.add_document(i, "small doc needle")
    build_time = time.monotonic() - start

    start = time.monotonic()
    results = eng.search("needle AND lorem", top_k=5)
    phrase = eng.search('"magna aliqua needle"')
    prefix = eng.search("dolo*")
    query_time = time.monotonic() - start

    assert ids(results) == {"big"}
    assert ids(phrase) == {"big"}
    assert "big" in ids(prefix)
    assert build_time < 10.0
    assert query_time < 5.0
