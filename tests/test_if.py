"""if / elif / else conditions."""

from tinytpl import Template


def render(src, **ctx):
    return Template(src).render(**ctx)


def test_if_true_false():
    tpl = Template("{% if ok %}yes{% endif %}")
    assert tpl.render(ok=True) == "yes"
    assert tpl.render(ok=False) == ""


def test_if_else():
    tpl = Template("{% if ok %}yes{% else %}no{% endif %}")
    assert tpl.render(ok=True) == "yes"
    assert tpl.render(ok=False) == "no"


def test_if_elif_else_chain():
    tpl = Template(
        "{% if n > 10 %}big{% elif n > 5 %}medium{% elif n > 0 %}small{% else %}zero{% endif %}"
    )
    assert tpl.render(n=20) == "big"
    assert tpl.render(n=7) == "medium"
    assert tpl.render(n=3) == "small"
    assert tpl.render(n=0) == "zero"


def test_elif_first_match_wins():
    tpl = Template("{% if n > 1 %}a{% elif n > 0 %}b{% endif %}")
    assert tpl.render(n=5) == "a"


def test_nested_if():
    tpl = Template(
        "{% if a %}{% if b %}ab{% else %}a-only{% endif %}{% else %}none{% endif %}"
    )
    assert tpl.render(a=True, b=True) == "ab"
    assert tpl.render(a=True, b=False) == "a-only"
    assert tpl.render(a=False, b=True) == "none"


def test_if_truthiness():
    tpl = Template("{% if x %}t{% else %}f{% endif %}")
    assert tpl.render(x="") == "f"
    assert tpl.render(x="hi") == "t"
    assert tpl.render(x=[]) == "f"
    assert tpl.render(x=[1]) == "t"
    assert tpl.render(x=0) == "f"


def test_if_with_string_comparison():
    tpl = Template('{% if name == "bob" %}hi bob{% else %}stranger{% endif %}')
    assert tpl.render(name="bob") == "hi bob"
    assert tpl.render(name="alice") == "stranger"
