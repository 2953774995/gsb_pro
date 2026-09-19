"""Variable output, dotted lookup and missing-variable behaviour."""

import pytest

from tinytpl import Environment, Template, TplError


def test_simple_variable():
    assert Template("Hello {{ name }}!").render(name="world") == "Hello world!"


def test_variable_types():
    assert Template("{{ n }}").render(n=42) == "42"
    assert Template("{{ f }}").render(f=1.5) == "1.5"
    assert Template("{{ b }}").render(b=True) == "True"
    assert Template("{{ x }}").render(x=None) == ""


def test_dotted_lookup_dict():
    tpl = Template("{{ user.name }} / {{ user.age }}")
    assert tpl.render(user={"name": "ann", "age": 30}) == "ann / 30"


def test_dotted_lookup_deep():
    tpl = Template("{{ a.b.c }}")
    assert tpl.render(a={"b": {"c": "deep"}}) == "deep"


def test_numeric_index_lookup():
    tpl = Template("{{ items.0 }}-{{ items.2 }}")
    assert tpl.render(items=["a", "b", "c"]) == "a-c"


def test_mixed_lookup():
    tpl = Template("{{ users.1.name }}")
    assert tpl.render(users=[{"name": "x"}, {"name": "y"}]) == "y"


def test_object_attribute_lookup():
    class User(object):
        def __init__(self):
            self.name = "obj-ann"

    assert Template("{{ user.name }}").render(user=User()) == "obj-ann"


def test_missing_variable_default_empty():
    assert Template("[{{ missing }}]").render() == "[]"


def test_missing_nested_variable_default_empty():
    assert Template("[{{ a.b.c }}]").render(a={}) == "[]"


def test_missing_variable_strict_raises():
    tpl = Template("{{ missing }}", strict=True)
    with pytest.raises(TplError, match="undefined variable"):
        tpl.render()


def test_missing_variable_strict_environment():
    env = Environment(strict=True)
    tpl = env.from_string("{{ missing }}")
    with pytest.raises(TplError, match="undefined variable"):
        tpl.render()


def test_missing_attribute_strict_raises():
    tpl = Template("{{ user.name }}", strict=True)
    with pytest.raises(TplError, match="undefined variable"):
        tpl.render(user={})


def test_missing_variable_in_condition_default_is_falsy():
    assert Template("{% if missing %}yes{% else %}no{% endif %}").render() == "no"


def test_missing_variable_in_condition_strict_raises():
    tpl = Template("{% if missing %}yes{% endif %}", strict=True)
    with pytest.raises(TplError):
        tpl.render()


def test_render_accepts_dict_and_kwargs():
    tpl = Template("{{ a }}-{{ b }}")
    assert tpl.render({"a": 1}, b=2) == "1-2"


def test_undefined_variable_name_in_error():
    tpl = Template("{{ nope }}", strict=True)
    with pytest.raises(TplError, match="nope"):
        tpl.render()
