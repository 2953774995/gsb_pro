import pytest

from minisearch import SearchEngine, SearchError


@pytest.fixture
def engine():
    eng = SearchEngine()
    eng.add_document(1, "python web server framework")
    eng.add_document(2, "python data science machine learning")
    eng.add_document(3, "java web server application")
    eng.add_document(4, "rust systems programming language")
    return eng


def ids(results):
    return [r["doc_id"] for r in results]


class TestBoolean:
    def test_and(self, engine):
        assert ids(engine.search("python AND web")) == [1]

    def test_or(self, engine):
        assert sorted(ids(engine.search("python OR java", top_k=0))) == [1, 2, 3]

    def test_not_unary(self, engine):
        result = ids(engine.search("web AND NOT java", top_k=0))
        assert result == [1]

    def test_not_alone(self, engine):
        result = ids(engine.search("NOT python", top_k=0))
        assert sorted(result) == [3, 4]

    def test_parentheses_grouping(self, engine):
        result = ids(engine.search("python AND (web OR data)", top_k=0))
        assert sorted(result) == [1, 2]

    def test_and_binds_tighter_than_or(self, engine):
        # parsed as: java OR (python AND web)
        result = ids(engine.search("java OR python AND web", top_k=0))
        assert sorted(result) == [1, 3]

    def test_parentheses_override_precedence(self, engine):
        result = ids(engine.search("(java OR python) AND web", top_k=0))
        assert sorted(result) == [1, 3]

    def test_not_with_group(self, engine):
        result = ids(engine.search("web AND NOT (java OR framework)", top_k=0))
        assert result == []

    def test_operators_case_insensitive(self, engine):
        assert ids(engine.search("python and web")) == [1]

    def test_implicit_and_for_adjacent_terms(self, engine):
        assert ids(engine.search("python web")) == [1]

    def test_nested_parentheses(self, engine):
        result = engine.search("((python AND web) OR rust) AND NOT java", top_k=0)
        assert sorted(ids(result)) == [1, 4]


class TestPhraseAndPrefix:
    def test_phrase_matches_adjacent(self, engine):
        assert ids(engine.search('"web server"', top_k=0)) == [1, 3]

    def test_phrase_rejects_non_adjacent(self):
        eng = SearchEngine()
        eng.add_document(1, "server side web rendering")
        assert eng.search('"web server"') == []

    def test_phrase_with_stemming(self):
        eng = SearchEngine()
        eng.add_document(1, "the web servers are running")
        assert ids(eng.search('"web server"')) == [1]

    def test_phrase_case_insensitive(self, engine):
        assert ids(engine.search('"Web Server"', top_k=0)) == [1, 3]

    def test_chinese_phrase(self):
        eng = SearchEngine()
        eng.add_document(1, "我爱自然语言处理技术")
        eng.add_document(2, "自然语言很有趣")
        assert ids(eng.search('"自然语言"', top_k=0)) == [1, 2]
        assert ids(eng.search('"语言处理"', top_k=0)) == [1]

    def test_prefix_query(self, engine):
        assert ids(engine.search("fram*")) == [1]

    def test_prefix_matches_multiple_terms(self):
        eng = SearchEngine()
        eng.add_document(1, "program programs programming")
        eng.add_document(2, "python")
        assert ids(eng.search("program*")) == [1]

    def test_prefix_no_match(self, engine):
        assert engine.search("zzz*") == []

    def test_prefix_in_boolean(self, engine):
        result = engine.search("mach* AND python", top_k=0)
        assert ids(result) == [2]


class TestInvalidQueries:
    @pytest.mark.parametrize("query", [
        "", "   ", "AND python", "python AND", "OR web", "python OR",
        "python AND OR web", "(python", "python)", "()", "NOT",
        '"unterminated', "*", "*term", "python AND ()",
    ])
    def test_invalid_queries_raise(self, engine, query):
        with pytest.raises(SearchError):
            engine.search(query)

    def test_error_has_reason(self, engine):
        with pytest.raises(SearchError) as exc_info:
            engine.search("AND python")
        assert str(exc_info.value)

    def test_stop_word_only_query_raises(self, engine):
        with pytest.raises(SearchError):
            engine.search("the")

    def test_non_string_query_raises(self, engine):
        with pytest.raises(SearchError):
            engine.search(123)
