import pytest

from minisearch import SearchEngine, SearchError
from minisearch.query import parse


# --------------------------------------------------------------------- #
# parser structure
# --------------------------------------------------------------------- #

def test_parse_term_and_operators():
    assert parse("python") == ("term", "python")
    assert parse("a AND b") == ("and", ("term", "a"), ("term", "b"))
    assert parse("a OR b") == ("or", ("term", "a"), ("term", "b"))
    assert parse("NOT a") == ("not", ("term", "a"))


def test_parse_precedence_not_and_or():
    # NOT > AND > OR:  a OR b AND NOT c  ==  a OR (b AND (NOT c))
    assert parse("a OR b AND NOT c") == (
        "or",
        ("term", "a"),
        ("and", ("term", "b"), ("not", ("term", "c"))),
    )


def test_parse_parentheses_override_precedence():
    assert parse("(a OR b) AND c") == (
        "and",
        ("or", ("term", "a"), ("term", "b")),
        ("term", "c"),
    )


def test_parse_phrase_and_prefix():
    assert parse('"hello world"') == ("phrase", "hello world")
    assert parse("serv*") == ("prefix", "serv")


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "AND python",          # leading binary operator
        "python AND",          # dangling operator
        "OR python",
        "python AND OR web",   # missing operand
        "(python",             # unbalanced '('
        "python)",             # unbalanced ')'
        "()",                  # empty group
        '"unterminated',       # missing closing quote
        '""',                  # empty phrase
        "*",                   # empty prefix
        "te*rm",               # '*' not at end
        "NOT",                 # NOT without operand
    ],
)
def test_invalid_queries_raise(bad):
    with pytest.raises(SearchError):
        parse(bad)


def test_error_messages_have_reason():
    with pytest.raises(SearchError, match="empty query"):
        parse("")
    with pytest.raises(SearchError, match="closing parenthesis"):
        parse("(python")


# --------------------------------------------------------------------- #
# boolean semantics over a real engine
# --------------------------------------------------------------------- #

@pytest.fixture
def engine():
    eng = SearchEngine()
    eng.add_document(1, "python web server")
    eng.add_document(2, "python web framework")
    eng.add_document(3, "java server")
    eng.add_document(4, "ruby web")
    return eng


def ids(results):
    return {hit["doc_id"] for hit in results}


def test_and(engine):
    assert ids(engine.search("python AND web")) == {1, 2}
    assert ids(engine.search("python AND server")) == {1}


def test_or(engine):
    assert ids(engine.search("java OR ruby")) == {3, 4}


def test_not(engine):
    assert ids(engine.search("web AND NOT python")) == {4}
    assert ids(engine.search("NOT python")) == {3, 4}


def test_parentheses(engine):
    assert ids(engine.search("python AND (web OR server)")) == {1, 2}
    assert ids(engine.search("(python OR java) AND server")) == {1, 3}


def test_not_applies_to_subexpression(engine):
    assert ids(engine.search("NOT (python OR java)")) == {4}


def test_boolean_results_sorted_by_score(engine):
    results = engine.search("python OR web")
    scores = [hit["score"] for hit in results]
    assert scores == sorted(scores, reverse=True)
    # doc 1 and 2 contain both terms -> outrank single-term docs
    assert {hit["doc_id"] for hit in results[:2]} == {1, 2}
