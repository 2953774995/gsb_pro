"""自实现模板引擎的测试。"""
import pytest

from mdsite.errors import MdsiteError
from mdsite.template import render


def test_variable_substitution():
    assert render("Hello {{ name }}!", {"name": "世界"}) == "Hello 世界!"


def test_dotted_lookup():
    ctx = {"page": {"title": "T"}}
    assert render("{{ page.title }}", ctx) == "T"


def test_if_block():
    tpl = "{% if show %}yes{% endif %}"
    assert render(tpl, {"show": True}) == "yes"
    assert render(tpl, {"show": False}) == ""
    assert render(tpl, {"show": ""}) == ""


def test_for_block():
    tpl = "{% for x in items %}[{{ x }}]{% endfor %}"
    assert render(tpl, {"items": [1, 2, 3]}) == "[1][2][3]"


def test_for_with_dotted_item():
    tpl = "{% for p in pages %}{{ p.title }};{% endfor %}"
    ctx = {"pages": [{"title": "a"}, {"title": "b"}]}
    assert render(tpl, ctx) == "a;b;"


def test_nested_if_in_for():
    tpl = "{% for x in items %}{% if x %}+{% endif %}{% endfor %}"
    assert render(tpl, {"items": [0, 1, 2]}) == "++"


def test_undefined_variable_raises():
    with pytest.raises(MdsiteError, match="未定义"):
        render("{{ missing }}", {})


def test_unknown_tag_raises():
    with pytest.raises(MdsiteError, match="未知模板标签"):
        render("{% include x %}", {})


def test_unclosed_if_raises():
    with pytest.raises(MdsiteError, match="endif"):
        render("{% if x %}oops", {"x": 1})


def test_unclosed_for_raises():
    with pytest.raises(MdsiteError, match="endfor"):
        render("{% for x in y %}oops", {"y": []})


def test_no_leftover_markers_in_plain_text():
    assert render("no markers here", {}) == "no markers here"
