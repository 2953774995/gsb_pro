import pytest

from storelens.lexer import tokenize, KEYWORD, IDENT, STRING, NUMBER, OP, PUNCT, EOF
from storelens.errors import StorelensError


def types(tokens):
    return [t.type for t in tokens]


def values(tokens):
    return [t.value for t in tokens]


def test_keywords_case_insensitive():
    tokens = tokenize("select Select SELECT from From")
    assert types(tokens) == [KEYWORD] * 5 + [EOF]
    assert values(tokens)[:5] == ["SELECT", "SELECT", "SELECT", "FROM", "FROM"]


def test_identifiers_preserve_case():
    tokens = tokenize("MyTable _col1")
    assert types(tokens) == [IDENT, IDENT, EOF]
    assert values(tokens)[:2] == ["MyTable", "_col1"]


def test_string_literal_with_escaped_quote():
    tokens = tokenize("'it''s fine'")
    assert tokens[0].type == STRING
    assert tokens[0].value == "it's fine"


def test_empty_string():
    tokens = tokenize("''")
    assert tokens[0].value == ""


def test_unterminated_string_raises():
    with pytest.raises(StorelensError, match="unterminated string"):
        tokenize("'oops")


def test_integer_and_real_literals():
    tokens = tokenize("42 3.14 0.5 2e3 1.5e-2")
    assert values(tokens)[:5] == [42, 3.14, 0.5, 2000.0, 0.015]
    assert isinstance(tokens[0].value, int)
    assert isinstance(tokens[1].value, float)


def test_operators_and_punctuation():
    tokens = tokenize("= != <> < <= > >= + - * / % ( ) , ;")
    assert values(tokens)[:-1] == ["=", "!=", "<>", "<", "<=", ">", ">=",
                                   "+", "-", "*", "/", "%",
                                   "(", ")", ",", ";"]


def test_line_comment_ignored():
    tokens = tokenize("SELECT -- a comment\na")
    assert values(tokens)[:2] == ["SELECT", "a"]


def test_unexpected_character_raises():
    with pytest.raises(StorelensError, match="unexpected character"):
        tokenize("SELECT @")


def test_error_reports_line_and_column():
    with pytest.raises(StorelensError, match=r"line 2, column 3"):
        tokenize("SELECT a\n  @")


def test_eof_token_appended():
    tokens = tokenize("")
    assert tokens[-1].type == EOF
