"""解析器与 AST 结构测试：字面量、转义、字符类、量词、分组、交替。"""

from datamask import nodes
from datamask.parser import parse


def test_literal_concat():
    r = parse("abc")
    assert isinstance(r.ast, nodes.Concat)
    assert [n.ch for n in r.ast.children] == ["a", "b", "c"]


def test_empty_pattern():
    r = parse("")
    assert isinstance(r.ast, nodes.Empty)
    assert r.n_groups == 0


def test_anchors_and_dot():
    r = parse("^.$")
    kinds = [type(n).__name__ for n in r.ast.children]
    assert kinds == ["Anchor", "Any", "Anchor"]
    assert r.ast.children[0].kind == "bol"
    assert r.ast.children[2].kind == "eol"


def test_simple_escapes():
    r = parse(r"\n\t\r\\")
    chars = [n.ch for n in r.ast.children]
    assert chars == ["\n", "\t", "\r", "\\"]


def test_punctuation_escapes_are_literals():
    r = parse(r"\.\*\+\?\(\)\[\]\|")
    chars = [n.ch for n in r.ast.children]
    assert chars == list(".*+?()[]|")


def test_hex_escapes():
    r = parse(r"\x41B")
    assert r.ast.children[0].ch == "A"
    assert r.ast.children[1].ch == "B"
    r = parse(r"\u597D")
    assert r.ast.ch == "好"


def test_class_code_escapes_become_charclass():
    for code in "dDwWsS":
        r = parse("\\" + code)
        assert isinstance(r.ast, nodes.CharClass)
        assert r.ast.items == [("k", code)]
        assert r.ast.negated is False


def test_charclass_basic_and_negation():
    r = parse("[abc]")
    assert r.ast.items == [("c", "a"), ("c", "b"), ("c", "c")]
    assert r.ast.negated is False
    r = parse("[^abc]")
    assert r.ast.negated is True


def test_charclass_ranges():
    r = parse("[a-z0-9]")
    assert r.ast.items == [("r", "a", "z"), ("r", "0", "9")]


def test_charclass_leading_dash_and_bracket_are_literals():
    r = parse("[]a-]")
    assert ("c", "]") in r.ast.items
    assert ("c", "-") in r.ast.items
    assert ("c", "a") in r.ast.items


def test_charclass_escaped_dash():
    r = parse(r"[a\-z]")
    assert r.ast.items == [("c", "a"), ("c", "-"), ("c", "z")]


def test_charclass_class_code_inside():
    r = parse(r"[\dx]")
    assert ("k", "d") in r.ast.items
    assert ("c", "x") in r.ast.items


def test_charclass_hex_range():
    r = parse(r"[\x41-\x5A]")
    assert r.ast.items == [("r", "A", "Z")]


def test_quantifiers():
    r = parse("a*")
    assert (r.ast.lo, r.ast.hi, r.ast.greedy) == (0, None, True)
    r = parse("a+")
    assert (r.ast.lo, r.ast.hi) == (1, None)
    r = parse("a?")
    assert (r.ast.lo, r.ast.hi) == (0, 1)
    r = parse("a{3}")
    assert (r.ast.lo, r.ast.hi) == (3, 3)
    r = parse("a{2,}")
    assert (r.ast.lo, r.ast.hi) == (2, None)
    r = parse("a{2,5}")
    assert (r.ast.lo, r.ast.hi) == (2, 5)


def test_lazy_quantifiers():
    for pat in ("a*?", "a+?", "a??", "a{1,3}?"):
        r = parse(pat)
        assert r.ast.greedy is False, pat


def test_brace_not_quantifier_is_literal():
    r = parse("a{,3}")
    # {,3} 不是合法量词，按字面量处理
    assert isinstance(r.ast, nodes.Concat)
    assert r.ast.children[1].ch == "{"
    r = parse("a{b}")
    assert r.ast.children[1].ch == "{"


def test_group_numbering_left_paren_order():
    r = parse("(a)((b)(c))(?:d)(?P<n>e)")
    assert r.n_groups == 5
    assert r.group_names == {"n": 5}
    # 非捕获分组不占编号
    outer = r.ast.children[1]
    assert outer.index == 2
    assert outer.child.children[0].index == 3
    assert outer.child.children[1].index == 4


def test_alternation_structure():
    r = parse("a|b|c")
    assert isinstance(r.ast, nodes.Alt)
    assert len(r.ast.branches) == 3


def test_empty_alternation_branch():
    r = parse("a|")
    assert isinstance(r.ast, nodes.Alt)
    assert isinstance(r.ast.branches[1], nodes.Empty)


def test_alternation_binds_looser_than_concat():
    r = parse("ab|cd")
    assert isinstance(r.ast, nodes.Alt)
    assert all(isinstance(b, nodes.Concat) for b in r.ast.branches)


def test_repeat_binds_tighter_than_concat():
    r = parse("ab*")
    assert isinstance(r.ast, nodes.Concat)
    assert isinstance(r.ast.children[1], nodes.Repeat)
