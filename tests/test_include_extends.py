"""include 与 extends/block 模板继承。"""

import pytest

from tinytpl import DictLoader, Environment, TplError


def make_env(mapping, **kw):
    return Environment(DictLoader(mapping), **kw)


def test_include_basic():
    env = make_env({
        "main": "A[{% include \"part.html\" %}]B",
        "part.html": "P-{{ v }}",
    })
    assert env.get_template("main").render(v=1) == "A[P-1]B"


def test_include_sees_current_context():
    env = make_env({
        "main": "{% for x in items %}{% include \"row\" %}{% endfor %}",
        "row": "{{ loop.index }}={{ x }};",
    })
    assert env.get_template("main").render(items=["a", "b"]) == "1=a;2=b;"


def test_include_missing_template_raises():
    env = make_env({"main": "{% include \"nope\" %}"})
    with pytest.raises(TplError, match="template not found"):
        env.get_template("main").render()


def test_extends_basic_override():
    env = make_env({
        "base": "<head>{% block title %}Base{% endblock %}</head>"
                "<body>{% block content %}default{% endblock %}</body>",
        "child": "{% extends \"base\" %}"
                 "{% block title %}Child{% endblock %}"
                 "{% block content %}C{% endblock %}",
    })
    assert env.get_template("child").render() \
        == "<head>Child</head><body>C</body>"


def test_extends_partial_override_uses_parent_default():
    env = make_env({
        "base": "[{% block a %}A{% endblock %}][{% block b %}B{% endblock %}]",
        "child": "{% extends \"base\" %}{% block b %}b2{% endblock %}",
    })
    assert env.get_template("child").render() == "[A][b2]"


def test_extends_three_levels():
    env = make_env({
        "base": "{% block x %}base{% endblock %}",
        "mid": "{% extends \"base\" %}{% block x %}mid{% endblock %}",
        "top": "{% extends \"mid\" %}{% block x %}top{% endblock %}",
    })
    assert env.get_template("top").render() == "top"
    assert env.get_template("mid").render() == "mid"
    assert env.get_template("base").render() == "base"


def test_extends_context_passed_through():
    env = make_env({
        "base": "Hello {{ name }}, {% block body %}?{% endblock %}",
        "child": "{% extends \"base\" %}{% block body %}{{ name }}!{% endblock %}",
    })
    assert env.get_template("child").render(name="Ann") == "Hello Ann, Ann!"


def test_extends_missing_parent_raises():
    env = make_env({"child": "{% extends \"ghost\" %}"})
    with pytest.raises(TplError, match="template not found"):
        env.get_template("child").render()


def test_duplicate_block_in_one_template_raises():
    env = make_env({
        "bad": "{% block a %}1{% endblock %}{% block a %}2{% endblock %}",
    })
    with pytest.raises(TplError, match="duplicate block"):
        env.get_template("bad")


def test_extends_not_first_tag_raises():
    env = make_env({
        "base": "x",
        "bad": "text{% extends \"base\" %}",
    })
    with pytest.raises(TplError, match="first tag"):
        env.get_template("bad")


def test_extends_inside_if_raises():
    env = make_env({
        "base": "x",
        "bad": "{% if a %}{% extends \"base\" %}{% endif %}",
    })
    with pytest.raises(TplError, match="top-level"):
        env.get_template("bad")


def test_block_with_loop_inside():
    env = make_env({
        "base": "{% block list %}{% endblock %}",
        "child": "{% extends \"base\" %}{% block list %}"
                 "{% for i in items %}{{ i }}{% endfor %}"
                 "{% endblock %}",
    })
    assert env.get_template("child").render(items=[1, 2, 3]) == "123"


def test_child_non_block_content_ignored():
    # 继承时子模板 block 之外的内容不输出（与 Jinja 一致）
    env = make_env({
        "base": "<{% block b %}B{% endblock %}>",
        "child": "{% extends \"base\" %}junk{% block b %}X{% endblock %}",
    })
    assert env.get_template("child").render() == "<X>"


def test_endblock_with_matching_name():
    env = make_env({
        "base": "{% block a %}A{% endblock a %}",
    })
    assert env.get_template("base").render() == "A"


def test_endblock_name_mismatch_raises():
    env = make_env({
        "bad": "{% block a %}A{% endblock b %}",
    })
    with pytest.raises(TplError, match="does not match"):
        env.get_template("bad")
