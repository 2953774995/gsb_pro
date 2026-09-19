"""if / elif / else 条件渲染。"""

from tinytpl import Template


def test_if_true_and_false():
    tpl = Template("{% if cond %}yes{% endif %}")
    assert tpl.render(cond=True) == "yes"
    assert tpl.render(cond=False) == ""


def test_if_else():
    tpl = Template("{% if cond %}A{% else %}B{% endif %}")
    assert tpl.render(cond=1) == "A"
    assert tpl.render(cond=0) == "B"


def test_if_elif_else_chain():
    tpl = Template(
        "{% if n == 1 %}one"
        "{% elif n == 2 %}two"
        "{% elif n == 3 %}three"
        "{% else %}many{% endif %}")
    assert tpl.render(n=1) == "one"
    assert tpl.render(n=2) == "two"
    assert tpl.render(n=3) == "three"
    assert tpl.render(n=9) == "many"


def test_nested_if():
    tpl = Template(
        "{% if a %}{% if b %}AB{% else %}A{% endif %}"
        "{% else %}{% if b %}B{% else %}none{% endif %}{% endif %}")
    assert tpl.render(a=True, b=True) == "AB"
    assert tpl.render(a=True, b=False) == "A"
    assert tpl.render(a=False, b=True) == "B"
    assert tpl.render(a=False, b=False) == "none"


def test_if_with_expression_condition():
    tpl = Template("{% if n >= 10 and n < 20 %}teen{% endif %}")
    assert tpl.render(n=15) == "teen"
    assert tpl.render(n=25) == ""


def test_missing_variable_is_falsy():
    tpl = Template("{% if missing %}x{% else %}empty{% endif %}")
    assert tpl.render() == "empty"
