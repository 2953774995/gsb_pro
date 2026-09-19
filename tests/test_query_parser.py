"""Query language: precedence, parentheses, phrase/prefix, error cases."""

import pytest

from minisearch.errors import SearchError
from minisearch.query import And, Not, Or, Phrase, Prefix, Term, parse


def test_single_term():
    assert parse("python") == Term("python")


def test_and_or_not_operators():
    assert parse("a AND b") == And(Term("a"), Term("b"))
    assert parse("a OR b") == Or(Term("a"), Term("b"))
    assert parse("NOT a") == Not(Term("a"))


def test_operators_are_case_insensitive():
    assert parse("a and b") == And(Term("a"), Term("b"))
    assert parse("a or NOT b") == Or(Term("a"), Not(Term("b")))


def test_precedence_not_then_and_then_or():
    assert parse("a OR b AND c") == Or(Term("a"), And(Term("b"), Term("c")))
    assert parse("a AND NOT b OR c") == Or(And(Term("a"), Not(Term("b"))), Term("c"))


def test_parentheses_override_precedence():
    assert parse("(a OR b) AND c") == And(Or(Term("a"), Term("b")), Term("c"))
    assert parse("NOT (a OR b)") == Not(Or(Term("a"), Term("b")))


def test_left_associativity():
    assert parse("a AND b AND c") == And(And(Term("a"), Term("b")), Term("c"))


def test_phrase():
    assert parse('"exact phrase"') == Phrase("exact phrase")
    assert parse('a AND "b c"') == And(Term("a"), Phrase("b c"))


def test_prefix():
    assert parse("py*") == Prefix("py")
    assert parse("py* AND web") == And(Prefix("py"), Term("web"))


def test_chinese_term():
    assert parse("搜索引擎") == Term("搜索引擎")


@pytest.mark.parametrize("bad", [
    "",                 # empty query
    "   ",              # whitespace only
    "AND python",       # leading binary operator
    "OR python",
    "python AND",       # trailing operator
    "python OR",
    "NOT",              # NOT without operand
    "(python",          # unbalanced (
    "python)",          # unbalanced )
    "()",               # empty group
    "python AND OR web",  # doubled operators
    '"unclosed phrase', # unbalanced quote
    "*",                # bare wildcard
])
def test_invalid_queries_raise_search_error(bad):
    with pytest.raises(SearchError) as excinfo:
        parse(bad)
    assert str(excinfo.value)  # error carries a reason


def test_non_string_query_rejected():
    with pytest.raises(SearchError):
        parse(None)


def test_implicit_and_between_adjacent_operands():
    assert parse("a b") == And(Term("a"), Term("b"))
    assert parse("a NOT b") == And(Term("a"), Not(Term("b")))
    assert parse("a (b OR c)") == And(Term("a"), Or(Term("b"), Term("c")))
