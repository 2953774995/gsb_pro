"""布尔查询语义、短语、前缀、非法查询错误。"""

import pytest

from minisearch import SearchEngine, SearchError


@pytest.fixture()
def engine():
    e = SearchEngine()
    e.add_document("d1", "python web server")
    e.add_document("d2", "python framework")
    e.add_document("d3", "java server")
    return e


def ids(results):
    return {r["doc_id"] for r in results}


def test_and(engine):
    assert ids(engine.search("python AND server")) == {"d1"}


def test_or(engine):
    assert ids(engine.search("python OR java")) == {"d1", "d2", "d3"}


def test_not_unary(engine):
    assert ids(engine.search("NOT python")) == {"d3"}


def test_and_not(engine):
    assert ids(engine.search("python AND NOT web")) == {"d2"}


def test_parentheses_grouping(engine):
    assert ids(engine.search("python AND (web OR framework)")) == {"d1", "d2"}
    assert ids(engine.search("(python OR java) AND server")) == {"d1", "d3"}


def test_and_precedence_over_or(engine):
    # java OR (python AND web)
    assert ids(engine.search("java OR python AND web")) == {"d1", "d3"}


def test_implicit_and(engine):
    assert ids(engine.search("python web")) == {"d1"}


def test_operators_case_insensitive(engine):
    assert ids(engine.search("python and server")) == {"d1"}
    assert ids(engine.search("python or java")) == {"d1", "d2", "d3"}


def test_not_with_parentheses(engine):
    assert ids(engine.search("NOT (python OR java)")) == set()


def test_double_not(engine):
    assert ids(engine.search("NOT NOT python")) == {"d1", "d2"}


# ------------------------------------------------------------ 短语查询

@pytest.fixture()
def phrase_engine():
    e = SearchEngine()
    e.add_document("fox", "the quick brown fox jumps over the lazy dog")
    e.add_document("other", "quick fox brown")
    e.add_document("cn", "我爱北京天安门")
    return e


def test_phrase_match(phrase_engine):
    assert ids(phrase_engine.search('"quick brown"')) == {"fox"}
    assert ids(phrase_engine.search('"brown fox"')) == {"fox"}


def test_phrase_no_match_when_not_adjacent(phrase_engine):
    assert ids(phrase_engine.search('"quick fox"')) == {"other"}
    assert ids(phrase_engine.search('"quick brown fox jumps"')) == {"fox"}
    assert phrase_engine.search('"brown quick"') == []


def test_phrase_chinese(phrase_engine):
    assert ids(phrase_engine.search('"北京天"')) == {"cn"}
    assert phrase_engine.search('"京北"') == []


def test_phrase_combined_with_boolean(phrase_engine):
    assert ids(phrase_engine.search('"quick brown" AND fox')) == {"fox"}


# ------------------------------------------------------------ 前缀查询

def test_prefix(engine):
    assert ids(engine.search("serv*")) == {"d1", "d3"}
    assert ids(engine.search("pyt*")) == {"d1", "d2"}
    assert ids(engine.search("fram*")) == {"d2"}


def test_prefix_no_match(engine):
    assert engine.search("zzz*") == []


def test_prefix_combined(engine):
    assert ids(engine.search("serv* AND NOT java")) == {"d1"}


# ------------------------------------------------------------ 非法查询

@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "AND python",
        "python AND",
        "OR",
        "python OR",
        "NOT",
        "(python",
        "python)",
        "()",
        '"unterminated',
        '""',
        "a*b",
        "*",
        "python AND OR server",
    ],
)
def test_invalid_queries_raise(engine, bad):
    with pytest.raises(SearchError):
        engine.search(bad)


def test_error_has_reason(engine):
    with pytest.raises(SearchError) as exc_info:
        engine.search("python AND")
    assert str(exc_info.value)
