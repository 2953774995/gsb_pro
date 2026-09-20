"""Pattern/Match API 测试：search/match/fullmatch/findall/finditer 与结果对象。"""

import pytest

from datamask import IGNORECASE, Pattern, compile


def test_compile_returns_pattern():
    p = compile("abc")
    assert isinstance(p, Pattern)
    assert p.pattern == "abc"
    assert p.flags == 0


def test_compile_with_flags():
    p = compile("abc", IGNORECASE)
    assert p.flags & IGNORECASE


def test_match_vs_search():
    p = compile("abc")
    assert p.match("xxabc") is None
    assert p.match("abcxx").span() == (0, 3)
    assert p.search("xxabc").span() == (2, 5)


def test_fullmatch():
    p = compile("a+b")
    assert p.fullmatch("aab") is not None
    assert p.fullmatch("aabb") is None
    assert p.fullmatch("xaab") is None
    # 交替需要回溯才能完整匹配
    assert compile("a|ab").fullmatch("ab") is not None


def test_findall_no_groups():
    assert compile(r"\d+").findall("a1b22c333") == ["1", "22", "333"]
    assert compile("x").findall("abc") == []


def test_findall_one_group():
    assert compile(r"(\d)\.").findall("1.2.3.") == ["1", "2", "3"]


def test_findall_multiple_groups():
    assert compile(r"(\d)(\w)").findall("1a2b") == [("1", "a"), ("2", "b")]


def test_finditer_is_lazy_iterator():
    it = compile(r"\d").finditer("1a2b3")
    assert iter(it) is it  # 是迭代器（惰性）
    assert next(it).group() == "1"
    assert [m.group() for m in it] == ["2", "3"]


def test_finditer_spans_non_overlapping():
    spans = [m.span() for m in compile("aa").finditer("aaaa")]
    assert spans == [(0, 2), (2, 4)]


def test_match_object_accessors():
    m = compile(r"(?P<w>\w+)@(?P<d>\w+)").search("x ab@cd y")
    assert m.group() == "ab@cd"
    assert m.group(0) == "ab@cd"
    assert m.group(1) == "ab"
    assert m.group("d") == "cd"
    assert m.group(1, 2) == ("ab", "cd")
    assert m.groups() == ("ab", "cd")
    assert m.start() == 2
    assert m.end() == 7
    assert m.start(2) == 5
    assert m.end("w") == 4
    assert m.span() == (2, 7)
    assert m.string == "x ab@cd y"
    assert m.re.pattern == r"(?P<w>\w+)@(?P<d>\w+)"


def test_match_invalid_group_raises():
    m = compile("(a)").search("a")
    with pytest.raises(IndexError):
        m.group(2)
    with pytest.raises(IndexError):
        m.group("nope")


def test_groups_default():
    m = compile("(a)|(b)").search("a")
    assert m.groups() == ("a", None)
    assert m.groups(default="-") == ("a", "-")


def test_non_string_input_raises_typeerror():
    with pytest.raises(TypeError):
        compile("a").search(123)
    with pytest.raises(TypeError):
        compile(123)


def test_pattern_repr():
    assert "abc" in repr(compile("abc"))
