"""End-to-end engine behaviour: boolean semantics, phrase/prefix, Chinese,
top_k, removal, overwrite, snippets, error handling."""

import pytest

from minisearch import SearchEngine, SearchError

DOCS = {
    1: "python web server framework",
    2: "python data science machine learning",
    3: "java web server spring framework",
    4: "搜索引擎 全文检索 中文分词",
}


@pytest.fixture
def engine():
    e = SearchEngine()
    for doc_id, text in DOCS.items():
        e.add_document(doc_id, text)
    return e


def ids(results):
    return [r.doc_id for r in results]


# --------------------------------------------------------------------- #
# boolean semantics
# --------------------------------------------------------------------- #
def test_and(engine):
    assert ids(engine.search("python AND web")) == [1]


def test_or(engine):
    assert set(ids(engine.search("python OR java"))) == {1, 2, 3}


def test_not(engine):
    assert ids(engine.search("web AND NOT java")) == [1]


def test_not_only_query(engine):
    assert set(ids(engine.search("NOT python"))) == {3, 4}


def test_parentheses_grouping(engine):
    assert set(ids(engine.search("python AND (web OR science)"))) == {1, 2}
    # Without grouping the precedence changes the meaning.
    assert set(ids(engine.search("python AND web OR science"))) == {1, 2}
    assert set(ids(engine.search("(python OR java) AND server"))) == {1, 3}


def test_complex_boolean_query_sorted_by_score(engine):
    # AND binds tighter than OR: python OR (java AND NOT spring).
    results = engine.search("python OR java AND NOT spring")
    assert set(ids(results)) == {1, 2}
    # Explicit grouping: every python/java doc without "spring".
    results = engine.search("(python OR java) AND NOT spring")
    assert set(ids(results)) == {1, 2}
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_case_insensitive(engine):
    assert ids(engine.search("PYTHON AND WeB")) == [1]


def test_stemmed_matching(engine):
    # "frameworks" stems to "framework".
    assert set(ids(engine.search("frameworks"))) == {1, 3}


# --------------------------------------------------------------------- #
# phrase and prefix
# --------------------------------------------------------------------- #
def test_phrase_requires_adjacency():
    e = SearchEngine()
    e.add_document(1, "exact phrase appears here")
    e.add_document(2, "exact match phrase")
    assert ids(e.search('"exact phrase"')) == [1]


def test_phrase_no_match_returns_empty(engine):
    assert engine.search('"server python"') == []


def test_prefix_query(engine):
    assert ids(engine.search("machin*")) == [2]
    assert set(ids(engine.search("frame*"))) == {1, 3}


def test_prefix_no_match(engine):
    assert engine.search("zzz*") == []


# --------------------------------------------------------------------- #
# Chinese
# --------------------------------------------------------------------- #
def test_chinese_query_hits(engine):
    assert ids(engine.search("搜索引擎")) == [4]
    assert ids(engine.search("中文")) == [4]
    assert ids(engine.search("检索")) == [4]


def test_mixed_chinese_english_query():
    e = SearchEngine()
    e.add_document(1, "Python是一种编程语言")
    assert ids(e.search("Python语言")) == [1]


# --------------------------------------------------------------------- #
# top_k / empty cases
# --------------------------------------------------------------------- #
def test_top_k_truncates(engine):
    results = engine.search("python OR java", top_k=2)
    assert len(results) == 2


def test_top_k_zero_returns_all(engine):
    results = engine.search("python OR java", top_k=0)
    assert len(results) == 3


def test_negative_top_k_rejected(engine):
    with pytest.raises(SearchError):
        engine.search("python", top_k=-1)


def test_no_match_returns_empty_list(engine):
    assert engine.search("nonexistentterm") == []


def test_empty_index_returns_empty_list():
    assert SearchEngine().search("python") == []


def test_empty_query_raises(engine):
    with pytest.raises(SearchError):
        engine.search("")
    with pytest.raises(SearchError):
        engine.search("   ")


def test_invalid_query_raises(engine):
    with pytest.raises(SearchError):
        engine.search("python AND")
    with pytest.raises(SearchError):
        engine.search("(python OR")


# --------------------------------------------------------------------- #
# document management
# --------------------------------------------------------------------- #
def test_document_count(engine):
    assert engine.document_count() == 4


def test_remove_document_updates_results(engine):
    assert engine.remove_document(1) is True
    assert engine.document_count() == 3
    assert engine.search("python AND web") == []
    assert ids(engine.search("python")) == [2]
    # No residue: the term only existed in the removed document combo.
    assert engine.remove_document(2) is True
    assert engine.search("python") == []
    assert engine.remove_document(999) is False


def test_readd_same_id_overwrites(engine):
    engine.add_document(1, "totally different content")
    assert engine.document_count() == 4
    assert ids(engine.search("python")) == [2]      # old content gone
    assert ids(engine.search("different")) == [1]   # new content indexed


def test_int_and_str_doc_ids():
    e = SearchEngine()
    e.add_document(1, "alpha")
    e.add_document("1", "alpha beta")
    assert e.document_count() == 2
    e.remove_document(1)
    assert ids(e.search("alpha")) == ["1"]


def test_invalid_doc_id_type_rejected():
    e = SearchEngine()
    with pytest.raises(TypeError):
        e.add_document(1.5, "text")


# --------------------------------------------------------------------- #
# snippets
# --------------------------------------------------------------------- #
def test_snippet_contains_hit_and_is_bounded():
    e = SearchEngine()
    text = "alpha " * 30 + "targetword " + "omega " * 30
    e.add_document(1, text)
    (result,) = e.search("targetword", with_snippet=True)
    assert "targetword" in result.snippet
    assert len(result.snippet) <= 80 + 6  # window plus two ellipses


def test_snippet_none_when_disabled(engine):
    (result,) = engine.search("python", top_k=1)
    assert result.snippet is None


def test_snippet_fallback_without_literal_hit(engine):
    # NOT-query results have no literal term in the doc; still get a snippet.
    results = engine.search("NOT python", with_snippet=True)
    assert all(r.snippet for r in results)


def test_implicit_and_in_boolean_query(engine):
    assert ids(engine.search("python (web OR server) NOT java")) == [1]
