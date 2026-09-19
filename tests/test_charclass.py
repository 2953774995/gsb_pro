"""Character classes: ranges, negation, shorthands inside classes, edges."""

import pytest

import rex
from rex.errors import RegexError


def test_plain_class_membership():
    p = rex.compile("[abc]+")
    assert p.findall("abcxabc") == ["abc", "abc"]
    assert rex.compile("[a]").fullmatch("a") is not None
    assert rex.compile("[a]").fullmatch("b") is None


def test_class_range():
    p = rex.compile("[a-z0-9]+")
    assert p.findall("ab12!cd34") == ["ab12", "cd34"]
    assert rex.compile("[A-F]").search("Z X A").group() == "A"


def test_negated_class():
    p = rex.compile("[^abc]+")
    assert p.findall("abcXYZabc") == ["XYZ"]
    assert rex.compile("[^0-9]+").findall("ab12cd") == ["ab", "cd"]


def test_negated_class_excludes_newline_only_when_not_listed():
    assert rex.compile("[^a]").search("\n").group() == "\n"


def test_empty_classes_are_errors():
    with pytest.raises(RegexError):
        rex.compile("[]")
    with pytest.raises(RegexError):
        rex.compile("[^]")


def test_closing_bracket_as_first_member():
    assert rex.compile("[]]").search("a]b").group() == "]"
    assert rex.compile("[^]]").findall("a]b]") == ["a", "b"]


def test_dash_at_edges_is_literal():
    assert rex.compile("[-a]").findall("-a-b") == ["-", "a", "-"]
    assert rex.compile("[a-]").fullmatch("-") is not None
    assert rex.compile("[a-z-]").search("x-y").group() == "x"


def test_shorthand_inside_class():
    assert rex.compile(r"[\d]+").findall("a12b3") == ["12", "3"]
    assert rex.compile(r"[a\d]+").findall("a1x9") == ["a1", "9"]
    assert rex.compile(r"[\w\s]+").fullmatch("a b c") is not None
    assert rex.compile(r"[^\d]+").findall("ab12cd") == ["ab", "cd"]


def test_escapes_inside_class():
    assert rex.compile(r"[\.\]]+").findall("].a.") == ["].", "."]
    assert rex.compile(r"[\\]").search(r"a\b").group() == "\\"
    assert rex.compile(r"[\x41-\x43]+").findall("ABCx") == ["ABC"]


def test_bad_range_reports_column():
    with pytest.raises(RegexError) as exc:
        rex.compile("[z-a]")
    assert exc.value.pos == 2  # the '-'
    with pytest.raises(RegexError) as exc:
        rex.compile("ab[9-3]")
    assert exc.value.pos == 4


def test_unterminated_class():
    with pytest.raises(RegexError) as exc:
        rex.compile("abc[0-9")
    assert exc.value.pos == 3
