"""变量替换、点号取值、缺失变量策略。"""

import pytest

from tinytpl import DictLoader, Environment, Template, TplError


def test_simple_variable():
    assert Template("Hello, {{ name }}!").render(name="Alice") \
        == "Hello, Alice!"


def test_render_with_kwargs_and_dict():
    tpl = Template("{{ a }}-{{ b }}")
    assert tpl.render({"a": 1}, b=2) == "1-2"
    assert tpl.render(a=1, b=2) == "1-2"


def test_dot_lookup_on_dict():
    ctx = {"user": {"name": "Bob", "age": 30}}
    assert Template("{{ user.name }} is {{ user.age }}").render(ctx) \
        == "Bob is 30"


def test_nested_dot_lookup():
    ctx = {"a": {"b": {"c": "deep"}}}
    assert Template("{{ a.b.c }}").render(ctx) == "deep"


def test_index_lookup_on_list():
    ctx = {"items": ["x", "y", "z"]}
    assert Template("{{ items.0 }}{{ items.2 }}").render(ctx) == "xz"


def test_mixed_lookup():
    ctx = {"users": [{"name": "n0"}, {"name": "n1"}]}
    assert Template("{{ users.1.name }}").render(ctx) == "n1"


def test_missing_variable_renders_empty_by_default():
    assert Template("[{{ nothing }}]").render() == "[]"


def test_missing_attribute_renders_empty_by_default():
    assert Template("[{{ user.name }}]").render(user={}) == "[]"


def test_missing_variable_strict_raises():
    with pytest.raises(TplError, match="undefined variable 'nothing'"):
        Template("{{ nothing }}", strict=True).render()


def test_missing_attribute_strict_raises():
    with pytest.raises(TplError):
        Template("{{ user.name }}", strict=True).render(user={})


def test_strict_via_environment():
    env = Environment(DictLoader({"t": "{{ oops }}"}), strict=True)
    with pytest.raises(TplError):
        env.get_template("t").render()


def test_loop_variable_does_not_leak():
    tpl = Template("{% for x in items %}{{ x }}{% endfor %}[{{ x }}]")
    assert tpl.render(items=[1, 2]) == "12[]"


def test_loop_variable_shadows_outer_and_restores():
    tpl = Template("{{ x }}|{% for x in items %}{{ x }}{% endfor %}|{{ x }}")
    assert tpl.render(x="outer", items=["i"]) == "outer|i|outer"


def test_none_and_boolean_literals():
    assert Template("{{ True }}{{ False }}{{ None }}").render() \
        == "TrueFalseNone"
