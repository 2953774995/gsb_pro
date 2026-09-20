"""Parser / scanner / escape tests: literals, escapes, classes, groups,
quantifiers, alternation, and all illegal-pattern error paths."""

import pytest

import datamask as dm
from datamask.nodes import (
    Alternate,
    Anchor,
    AnyChar,
    CharClass,
    Concat,
    Group,
    Literal,
    Repeat,
)
from datamask.parser import parse


def ast_of(pattern):
    return parse(pattern)[0]


# ---------------------------------------------------------------- literals
def test_single_literal():
    assert ast_of("a") == Literal("a")


def test_literal_concat():
    node = ast_of("abc")
    assert node == Concat([Literal("a"), Literal("b"), Literal("c")])


def test_empty_pattern_parses():
    assert ast_of("") == Concat([])


def test_literal_brace_is_literal_when_not_a_quantifier():
    node = ast_of("a{b}")
    assert isinstance(node, Concat)
    assert node.items[1] == Literal("{")


# ----------------------------------------------------------------- escapes
@pytest.mark.parametrize(
    "src,expected",
    [
        (r"\n", "\n"),
        (r"\t", "\t"),
        (r"\r", "\r"),
        (r"\\", "\\"),
        (r"\.", "."),
        (r"\*", "*"),
        (r"\+", "+"),
        (r"\?", "?"),
        (r"\(", "("),
        (r"\)", ")"),
        (r"\[", "["),
        (r"\]", "]"),
        (r"\|", "|"),
        (r"\x41", "A"),
        (r"\x7a", "z"),
        ("中", "中"),
        (r"\$", "$"),
        (r"\^", "^"),
    ],
)
def test_escape_literals(src, expected):
    assert ast_of(src) == Literal(expected)


def test_hex_escape_boundary():
    assert ast_of(r"\x00") == Literal("\x00")
    assert ast_of(r"\xff") == Literal("\xff")


def test_unknown_escape_raises_with_column():
    with pytest.raises(dm.PatternError) as ei:
        dm.compile(r"ab\q")
    assert "unknown escape" in str(ei.value)
    assert ei.value.column == 3


def test_trailing_backslash_raises():
    with pytest.raises(dm.PatternError) as ei:
        dm.compile("ab\\")
    assert "trailing backslash" in str(ei.value)
    assert ei.value.column == 3


def test_bad_hex_escape_raises():
    with pytest.raises(dm.PatternError):
        dm.compile(r"\x4")
    with pytest.raises(dm.PatternError):
        dm.compile(r"\xzz")
    with pytest.raises(dm.PatternError):
        dm.compile(r"\u12")


def test_backreference_not_supported():
    with pytest.raises(dm.PatternError) as ei:
        dm.compile(r"(a)\1")
    assert "not supported" in str(ei.value)


# ------------------------------------------------------------- char classes
def test_simple_class():
    node = ast_of("[abc]")
    assert node == CharClass((("range", "a", "a"),
                              ("range", "b", "b"),
                              ("range", "c", "c")), False)


def test_negated_class():
    node = ast_of("[^abc]")
    assert node.negated is True


def test_class_range():
    node = ast_of("[a-z0-9]")
    assert ("range", "a", "z") in node.items
    assert ("range", "0", "9") in node.items


def test_class_literal_bracket_first():
    node = ast_of("[]a]")
    assert ("range", "]", "]") in node.items


def test_class_dash_at_edges_is_literal():
    node = ast_of("[-a]")
    assert ("range", "-", "-") in node.items
    node = ast_of("[a-]")
    assert ("range", "-", "-") in node.items


def test_class_with_shorthand():
    node = ast_of(r"[\d_]")
    assert ("pred", "digit") in node.items


def test_empty_class_raises():
    with pytest.raises(dm.PatternError):
        dm.compile("[]")


def test_unterminated_class_raises_with_column():
    with pytest.raises(dm.PatternError) as ei:
        dm.compile("ab[cd")
    assert "unterminated character class" in str(ei.value)
    assert ei.value.column == 3


def test_bad_range_raises():
    with pytest.raises(dm.PatternError) as ei:
        dm.compile("[z-a]")
    assert "bad character range" in str(ei.value)


# --------------------------------------------------------------- quantifiers
def test_star_plus_quest():
    assert ast_of("a*") == Repeat(Literal("a"), 0, None, True)
    assert ast_of("a+") == Repeat(Literal("a"), 1, None, True)
    assert ast_of("a?") == Repeat(Literal("a"), 0, 1, True)


def test_lazy_suffixes():
    assert ast_of("a*?").greedy is False
    assert ast_of("a+?").greedy is False
    assert ast_of("a??").greedy is False
    assert ast_of("a{1,3}?").greedy is False


def test_brace_quantifiers():
    assert ast_of("a{3}") == Repeat(Literal("a"), 3, 3, True)
    assert ast_of("a{2,}") == Repeat(Literal("a"), 2, None, True)
    assert ast_of("a{2,5}") == Repeat(Literal("a"), 2, 5, True)


def test_quantifier_bounds():
    with pytest.raises(dm.PatternError) as ei:
        dm.compile("a{3,2}")
    assert "greater than max" in str(ei.value)
    assert ei.value.column == 2
    with pytest.raises(dm.PatternError) as ei:
        dm.compile("a{65536}")
    assert "too large" in str(ei.value)
    dm.compile("a{65535}")  # boundary allowed


def test_quantifier_without_atom_raises():
    with pytest.raises(dm.PatternError) as ei:
        dm.compile("*abc")
    assert "nothing to repeat" in str(ei.value)
    assert ei.value.column == 1


def test_double_quantifier_raises():
    with pytest.raises(dm.PatternError) as ei:
        dm.compile("a**")
    assert ei.value.column == 3


def test_quantifier_on_anchor_raises():
    with pytest.raises(dm.PatternError):
        dm.compile("^*")
    with pytest.raises(dm.PatternError):
        dm.compile("$+")


def test_brace_quantifier_without_atom_raises():
    with pytest.raises(dm.PatternError):
        dm.compile("{2}a")


# ------------------------------------------------------------------- groups
def test_capturing_group_numbering():
    _, ngroups, names = parse("(a)((b))(?:c)(?P<d>d)")
    assert ngroups == 4  # (?P<d>d) takes a number too, (?:c) does not
    assert names == {"d": 4}


def test_named_group():
    node = ast_of("(?P<word>ab)")
    assert isinstance(node, Group)
    assert node.name == "word"
    assert node.index == 1


def test_noncapturing_group():
    node = ast_of("(?:ab)")
    assert isinstance(node, Group)
    assert node.index is None


def test_empty_group_allowed():
    node = ast_of("()")
    assert isinstance(node, Group)


def test_duplicate_group_name_raises():
    with pytest.raises(dm.PatternError) as ei:
        dm.compile("(?P<x>a)(?P<x>b)")
    assert "duplicate group name" in str(ei.value)
    assert ei.value.column == 9


def test_unterminated_group_raises_with_column():
    with pytest.raises(dm.PatternError) as ei:
        dm.compile("ab(cd")
    assert "unterminated group" in str(ei.value)
    assert ei.value.column == 3


def test_unmatched_close_paren_raises_with_column():
    with pytest.raises(dm.PatternError) as ei:
        dm.compile("abc)")
    assert "unmatched ')'" in str(ei.value)
    assert ei.value.column == 4


def test_lookaround_not_supported():
    with pytest.raises(dm.PatternError) as ei:
        dm.compile("(?=a)b")
    assert "not supported" in str(ei.value)


def test_invalid_group_name_raises():
    with pytest.raises(dm.PatternError):
        dm.compile("(?P<1x>a)")


# --------------------------------------------------------------- alternation
def test_alternation_ast():
    node = ast_of("a|b|c")
    assert isinstance(node, Alternate)
    assert node.branches == [Literal("a"), Literal("b"), Literal("c")]


def test_empty_alternation_branch():
    node = ast_of("a|")
    assert isinstance(node, Alternate)
    assert node.branches[1] == Concat([])


# -------------------------------------------------------------- anchors/dot
def test_anchors_and_dot():
    node = ast_of("^a$")
    assert node.items[0] == Anchor("^")
    assert node.items[2] == Anchor("$")
    assert ast_of(".") == AnyChar()
