import pytest

from sqlq.errors import SqlqSyntaxError
from sqlq.lexer import (
    T_EOF, T_FLOAT, T_IDENT, T_INTEGER, T_KEYWORD, T_PUNCT, T_STAR, T_STRING,
    tokenize,
)


def kinds(sql):
    return [(t.kind, t.value) for t in tokenize(sql) if t.kind != T_EOF]


def test_keywords_are_case_insensitive():
    tokens = tokenize("SeLeCt FrOm WhErE")
    assert [t.value for t in tokens if t.kind == T_KEYWORD] == [
        "SELECT", "FROM", "WHERE"
    ]


def test_integer_and_float_literals():
    tokens = tokenize("1 42 3.14 .5 1e3 2.5E-2")
    values = [(t.kind, t.value) for t in tokens if t.kind != T_EOF]
    assert values == [
        (T_INTEGER, 1),
        (T_INTEGER, 42),
        (T_FLOAT, 3.14),
        (T_FLOAT, 0.5),
        (T_FLOAT, 1000.0),
        (T_FLOAT, 0.025),
    ]


def test_string_escaping():
    tokens = tokenize("'it''s ok' 'plain'")
    strings = [t.value for t in tokens if t.kind == T_STRING]
    assert strings == ["it's ok", "plain"]


def test_unterminated_string_reports_position():
    with pytest.raises(SqlqSyntaxError) as info:
        tokenize("select 'abc")
    assert "unterminated string" in str(info.value)
    assert info.value.line == 1


def test_unterminated_block_comment():
    with pytest.raises(SqlqSyntaxError):
        tokenize("/* never ends")


def test_comments_are_skipped():
    tokens = tokenize("select 1 -- a comment\n /* block */ from t")
    assert any(t.is_keyword("FROM") for t in tokens)
    assert all(t.kind != T_STRING for t in tokens)


def test_operators_including_generic_not_equal():
    tokens = tokenize("<= >= != <> = < > ( ) , ; . + - / * %")
    values = [t.value for t in tokens if t.kind in (T_PUNCT, T_STAR)]
    assert values == ["<=", ">=", "!=", "<>", "=", "<", ">",
                      "(", ")", ",", ";", ".", "+", "-", "/", "*", "%"]


def test_illegal_character():
    with pytest.raises(SqlqSyntaxError) as info:
        tokenize("select @ from t")
    assert info.value.column == 8


def test_malformed_exponent():
    with pytest.raises(SqlqSyntaxError):
        tokenize("1e")


def test_star_token_kind():
    tokens = tokenize("*")
    assert tokens[0].kind == T_STAR


    tokens = tokenize("")
    assert tokens[-1].kind == T_EOF
