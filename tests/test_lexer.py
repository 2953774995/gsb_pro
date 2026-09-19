import pytest

from sqlq.errors import SqlqError
from sqlq.lexer import tokenize


def simplify(text):
    return [(token.kind, token.value) for token in tokenize(text)
            if token.kind != "EOF"]


def test_keywords_case_insensitive_and_preserved_as_upper():
    tokens = simplify("select SELECT SeLeCt")
    assert tokens == [("KEYWORD", "SELECT")] * 3


def test_identifiers_and_numbers_and_strings():
    tokens = simplify("name_1 42 3.5 'abc'")
    assert tokens == [
        ("IDENT", "name_1"),
        ("NUMBER", 42),
        ("NUMBER", 3.5),
        ("STRING", "abc"),
    ]


def test_float_scientific_and_unary_sign_is_operator():
    tokens = simplify("1e3 2.5E-2 -7")
    assert tokens == [
        ("NUMBER", 1000.0),
        ("NUMBER", 0.025),
        ("PUNCT", "-"),
        ("NUMBER", 7),
    ]


def test_escaped_single_quote():
    tokens = simplify("'it''s ok'")
    assert tokens == [("STRING", "it's ok")]


def test_unterminated_string_reports_position():
    with pytest.raises(SqlqError) as info:
        tokenize("'abc")
    assert "unterminated string" in str(info.value)
    assert info.value.line == 1 and info.value.column == 1


def test_unexpected_character_error():
    with pytest.raises(SqlqError) as info:
        tokenize("SELECT @ FROM t;")
    assert info.value.column == 8


def test_multi_character_operators():
    assert simplify("<= >= != <> == =") == [
        ("PUNCT", "<="), ("PUNCT", ">="), ("PUNCT", "!="),
        ("PUNCT", "<>"), ("PUNCT", "=="), ("PUNCT", "="),
    ]


def test_line_and_block_comments_are_skipped():
    tokens = simplify("SELECT 1 -- tail\n /* block /* nested */ end */ + 2")
    assert tokens == [
        ("KEYWORD", "SELECT"), ("NUMBER", 1),
        ("PUNCT", "+"), ("NUMBER", 2),
    ]


def test_unterminated_block_comment():
    with pytest.raises(SqlqError):
        tokenize("/* never ends")


def test_position_tracks_newlines():
    tokens = tokenize("SELECT\n  x FROM t;")
    ident_x = next(token for token in tokens if token.value == "x")
    assert ident_x.line == 2 and ident_x.column == 3
