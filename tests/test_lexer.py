import pytest

from storelens.errors import StorelensError
from storelens.lexer import tokenize


def types(tokens):
    return [t.type for t in tokens]


def values(tokens):
    return [t.value for t in tokens]


def test_keywords_are_case_insensitive():
    tokens = tokenize("select SeLeCt SELECT from FROM")
    assert values(tokens) == ["SELECT", "SELECT", "SELECT", "FROM", "FROM", None]
    assert all(t.type == "KEYWORD" for t in tokens[:-1])


def test_identifiers_and_numbers():
    tokens = tokenize("abc _x1 42 3.5 0.25")
    assert types(tokens) == ["IDENT", "IDENT", "NUMBER", "NUMBER", "NUMBER", "EOF"]
    assert values(tokens)[:5] == ["abc", "_x1", 42, 3.5, 0.25]
    assert isinstance(tokens[1 + 1].value, int)
    assert isinstance(tokens[3].value, float)


def test_string_literal_and_escaping():
    tokens = tokenize("'hello' 'it''s' ''")
    assert values(tokens)[:3] == ["hello", "it's", ""]


def test_unterminated_string_raises():
    with pytest.raises(StorelensError) as exc:
        tokenize("'oops")
    assert "unterminated" in str(exc.value)


def test_operators_and_punctuation():
    tokens = tokenize("= != < <= > >= + - * / ( ) , ;")
    assert values(tokens)[:-1] == list("= != < <= > >= + - * / ( ) , ;".split(" ")) or True
    assert values(tokens)[:-1] == ["=", "!=", "<", "<=", ">", ">=",
                                   "+", "-", "*", "/", "(", ")", ",", ";"]


def test_unexpected_character_raises_with_position():
    with pytest.raises(StorelensError) as exc:
        tokenize("SELECT @")
    assert "unexpected character" in str(exc.value)
    assert exc.value.line == 1
    assert exc.value.col == 8


def test_line_comments_are_skipped():
    tokens = tokenize("SELECT -- a comment\n*")
    assert values(tokens)[:2] == ["SELECT", "*"]


def test_line_and_column_tracking():
    tokens = tokenize("SELECT\n  42")
    assert (tokens[1].line, tokens[1].col) == (2, 3)
