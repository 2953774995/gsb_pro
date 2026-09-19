import math

import pytest

from minisearch import SearchEngine, SearchError


def ids(results):
    return [r["doc_id"] for r in results]


class TestDocumentManagement:
    def test_add_and_count(self):
        eng = SearchEngine()
        assert eng.document_count() == 0
        eng.add_document(1, "hello world")
        eng.add_document("two", "你好世界")
        assert eng.document_count() == 2

    def test_readd_same_id_replaces(self):
        eng = SearchEngine()
        eng.add_document(1, "apple apple apple")
        eng.add_document(1, "banana")
        assert eng.document_count() == 1
        assert eng.search("apple") == []
        assert ids(eng.search("banana")) == [1]

    def test_remove_document(self):
        eng = SearchEngine()
        eng.add_document(1, "apple")
        assert eng.remove_document(1) is True
        assert eng.document_count() == 0
        assert eng.remove_document(1) is False

    def test_remove_leaves_no_residue(self):
        eng = SearchEngine()
        eng.add_document(1, "uniqueword apple")
        eng.add_document(2, "apple")
        eng.remove_document(1)
        assert eng.search("uniqueword") == []
        assert ids(eng.search("apple")) == [2]

    def test_remove_then_reindex_term_df_correct(self):
        eng = SearchEngine()
        eng.add_document(1, "apple")
        eng.add_document(2, "apple")
        eng.remove_document(1)
        eng.add_document(3, "apple")
        results = eng.search("apple", top_k=0)
        assert sorted(ids(results)) == [2, 3]
        # df is 2 of N=2 -> idf = log(1 + 2/2) = log(2)
        expected = (1 + math.log(1)) * math.log(2)
        assert results[0]["score"] == pytest.approx(expected)

    def test_doc_id_int_and_str(self):
        eng = SearchEngine()
        eng.add_document(1, "apple")
        eng.add_document("1", "apple")
        assert eng.document_count() == 2
        assert sorted(ids(eng.search("apple", top_k=0)), key=str) == [1, "1"]

    def test_invalid_doc_id_type(self):
        eng = SearchEngine()
        with pytest.raises(TypeError):
            eng.add_document(1.5, "text")
        with pytest.raises(TypeError):
            eng.add_document(None, "text")

    def test_invalid_text_type(self):
        eng = SearchEngine()
        with pytest.raises(TypeError):
            eng.add_document(1, b"bytes")


class TestScoring:
    def test_tfidf_formula_single_term(self):
        eng = SearchEngine()
        eng.add_document(1, "apple apple apple banana")
        eng.add_document(2, "apple cherry")
        results = {r["doc_id"]: r["score"] for r in eng.search("apple", top_k=0)}
        # N=2, df=2 -> idf = log(1 + 2/2) = log(2)
        idf = math.log(2)
        assert results[1] == pytest.approx((1 + math.log(3)) * idf)
        assert results[2] == pytest.approx((1 + math.log(1)) * idf)

    def test_higher_tf_ranks_first(self):
        eng = SearchEngine()
        eng.add_document(1, "apple " * 10)
        eng.add_document(2, "apple")
        eng.add_document(3, "banana")
        assert ids(eng.search("apple"))[0] == 1

    def test_rarer_term_scores_higher(self):
        eng = SearchEngine()
        eng.add_document(1, "common rare")
        eng.add_document(2, "common")
        eng.add_document(3, "common")
        results = eng.search("rare OR common", top_k=0)
        assert ids(results)[0] == 1

    def test_fixed_corpus_ordering(self):
        # Hand-computable corpus: query "apple"
        # N=3. doc1: tf=3, doc2: tf=1, doc3: no match. df=2.
        eng = SearchEngine()
        eng.add_document(1, "apple apple apple")
        eng.add_document(2, "apple banana")
        eng.add_document(3, "banana cherry")
        results = eng.search("apple", top_k=0)
        assert ids(results) == [1, 2]
        idf = math.log(1 + 3 / 2)
        assert results[0]["score"] == pytest.approx((1 + math.log(3)) * idf)
        assert results[1]["score"] == pytest.approx((1 + math.log(1)) * idf)

    def test_scores_descending(self):
        eng = SearchEngine()
        for i in range(1, 6):
            eng.add_document(i, "apple " * i)
        scores = [r["score"] for r in eng.search("apple", top_k=0)]
        assert scores == sorted(scores, reverse=True)


class TestSearchInterface:
    def test_top_k_truncation(self):
        eng = SearchEngine()
        for i in range(20):
            eng.add_document(i, "apple " * (i + 1))
        results = eng.search("apple")
        assert len(results) == 10  # default top_k
        assert len(eng.search("apple", top_k=3)) == 3
        assert len(eng.search("apple", top_k=0)) == 20

    def test_top_k_negative_raises(self):
        eng = SearchEngine()
        eng.add_document(1, "apple")
        with pytest.raises(SearchError):
            eng.search("apple", top_k=-1)

    def test_empty_index_returns_empty(self):
        eng = SearchEngine()
        assert eng.search("anything") == []

    def test_no_match_returns_empty(self):
        eng = SearchEngine()
        eng.add_document(1, "apple")
        assert eng.search("zebra") == []

    def test_result_structure(self):
        eng = SearchEngine()
        eng.add_document(1, "hello world")
        result = eng.search("hello")[0]
        assert result["doc_id"] == 1
        assert isinstance(result["score"], float)
        assert "snippet" not in result

    def test_case_insensitive_search(self):
        eng = SearchEngine()
        eng.add_document(1, "PyThOn Is GrEaT")
        assert ids(eng.search("python")) == [1]
        assert ids(eng.search("PYTHON")) == [1]

    def test_chinese_query_hits(self):
        eng = SearchEngine()
        eng.add_document(1, "我喜欢用搜索引擎查找资料")
        eng.add_document(2, "今天天气不错")
        assert ids(eng.search("搜索引擎")) == [1]
        assert ids(eng.search("搜索")) == [1]
        assert ids(eng.search("擎")) == [1]

    def test_mixed_query(self):
        eng = SearchEngine()
        eng.add_document(1, "使用Python开发搜索系统")
        assert ids(eng.search("python AND 搜索")) == [1]


class TestSnippets:
    def test_snippet_contains_hit(self):
        eng = SearchEngine()
        eng.add_document(1, "the quick brown fox jumps over the lazy dog")
        result = eng.search("fox", with_snippet=True)[0]
        assert "fox" in result["snippet"].lower()

    def test_snippet_max_80_chars_plus_ellipsis(self):
        eng = SearchEngine()
        text = "word " * 100 + "target " + "word " * 100
        eng.add_document(1, text)
        snippet = eng.search("target", with_snippet=True)[0]["snippet"]
        assert "target" in snippet
        assert len(snippet) <= 90  # 80 chars + ellipsis marks
        assert snippet.startswith("...")

    def test_snippet_short_document(self):
        eng = SearchEngine()
        eng.add_document(1, "short text")
        snippet = eng.search("short", with_snippet=True)[0]["snippet"]
        assert snippet == "short text"

    def test_snippet_chinese_hit(self):
        eng = SearchEngine()
        eng.add_document(1, "这是一段关于全文搜索引擎的中文文档内容")
        snippet = eng.search("搜索引擎", with_snippet=True)[0]["snippet"]
        assert "搜" in snippet or "索" in snippet
