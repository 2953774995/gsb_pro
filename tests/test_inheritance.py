"""Template inheritance (extends/block) and include."""

import pytest

from tinytpl import DictLoader, Environment, Template, TemplateNotFound, TplError


def make_env():
    return Environment(
        DictLoader(
            {
                "base.html": (
                    "<html><head><title>{% block title %}Base{% endblock %}</title></head>"
                    "<body>{% block content %}base content{% endblock %}</body></html>"
                ),
                "child.html": (
                    '{% extends "base.html" %}'
                    "{% block title %}Child{% endblock %}"
                    "{% block content %}child content{% endblock %}"
                ),
                "partial.html": "<li>{{ item }}</li>",
                "page.html": (
                    "<ul>{% for item in items %}{% include \"partial.html\" %}{% endfor %}</ul>"
                ),
                "mid.html": (
                    '{% extends "base.html" %}'
                    "{% block title %}Mid{% endblock %}"
                ),
                "grand.html": (
                    '{% extends "mid.html" %}'
                    "{% block content %}grand content{% endblock %}"
                ),
            }
        )
    )


def test_extends_overrides_blocks():
    env = make_env()
    out = env.get_template("child.html").render()
    assert out == (
        "<html><head><title>Child</title></head>"
        "<body>child content</body></html>"
    )


def test_extends_partial_override_keeps_parent_blocks():
    env = make_env()
    out = env.get_template("mid.html").render()
    assert "<title>Mid</title>" in out
    assert "<body>base content</body>" in out


def test_three_level_inheritance():
    env = make_env()
    out = env.get_template("grand.html").render()
    # title from mid, content from grand, skeleton from base
    assert "<title>Mid</title>" in out
    assert "<body>grand content</body>" in out


def test_block_with_endblock_name():
    env = Environment(
        DictLoader(
            {
                "b.html": "{% block x %}a{% endblock x %}",
                "c.html": '{% extends "b.html" %}{% block x %}over{% endblock x %}',
            }
        )
    )
    assert env.get_template("c.html").render() == "over"


def test_include():
    env = make_env()
    out = env.get_template("page.html").render(items=["a", "b"])
    assert out == "<ul><li>a</li><li>b</li></ul>"


def test_include_sees_current_context():
    env = Environment(
        DictLoader(
            {
                "p.html": "{{ prefix }}-{{ x }}",
                "main.html": '{% for x in xs %}{% include "p.html" %}{% endfor %}',
            }
        )
    )
    out = env.get_template("main.html").render(prefix="P", xs=[1, 2])
    assert out == "P-1P-2"


def test_include_with_variable_name():
    env = Environment(DictLoader({"a.html": "A", "m.html": '{% include which %}'}))
    assert env.get_template("m.html").render(which="a.html") == "A"


def test_missing_parent_template_raises():
    env = Environment(DictLoader({"c.html": '{% extends "nope.html" %}'}))
    with pytest.raises(TemplateNotFound):
        env.get_template("c.html").render()


def test_missing_include_raises():
    env = Environment(DictLoader({"m.html": '{% include "nope.html" %}'}))
    with pytest.raises(TemplateNotFound):
        env.get_template("m.html").render()


def test_template_not_found_is_tplerror():
    env = Environment(DictLoader({}))
    with pytest.raises(TplError):
        env.get_template("missing.html")


def test_duplicate_block_names_raise():
    with pytest.raises(TplError, match="duplicate block"):
        Template("{% block a %}1{% endblock %}{% block a %}2{% endblock %}")


def test_duplicate_block_names_in_loader_template():
    env = Environment(
        DictLoader({"bad.html": "{% block a %}1{% endblock %}{% block a %}2{% endblock %}"})
    )
    with pytest.raises(TplError, match="duplicate block"):
        env.get_template("bad.html")


def test_multiple_extends_raise():
    with pytest.raises(TplError, match="extends"):
        Template('{% extends "a" %}{% extends "b" %}')


def test_circular_extends_raises():
    env = Environment(
        DictLoader(
            {
                "a.html": '{% extends "b.html" %}{% block x %}a{% endblock %}',
                "b.html": '{% extends "a.html" %}{% block x %}b{% endblock %}',
            }
        )
    )
    with pytest.raises(TplError, match="circular"):
        env.get_template("a.html").render()


def test_recursive_include_raises():
    env = Environment(DictLoader({"r.html": '{% include "r.html" %}'}))
    with pytest.raises(TplError, match="circular"):
        env.get_template("r.html").render()


def test_block_content_uses_render_context():
    env = Environment(
        DictLoader(
            {
                "base.html": "{% block greeting %}hi{% endblock %}",
                "child.html": '{% extends "base.html" %}{% block greeting %}hi {{ name }}{% endblock %}',
            }
        )
    )
    assert env.get_template("child.html").render(name="ann") == "hi ann"


def test_standalone_template_with_loader():
    loader = DictLoader({"p.html": "partial!"})
    tpl = Template('{% include "p.html" %}', loader=loader)
    assert tpl.render() == "partial!"
