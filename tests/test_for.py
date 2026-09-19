"""for loops, loop helper variables, nesting and scoping."""

from tinytpl import Template


def test_basic_loop():
    tpl = Template("{% for x in items %}{{ x }}{% endfor %}")
    assert tpl.render(items=[1, 2, 3]) == "123"


def test_loop_empty():
    tpl = Template("[{% for x in items %}{{ x }}{% endfor %}]")
    assert tpl.render(items=[]) == "[]"


def test_loop_over_missing_variable_default():
    tpl = Template("[{% for x in missing %}{{ x }}{% endfor %}]")
    assert tpl.render() == "[]"


def test_loop_index():
    tpl = Template("{% for x in items %}{{ loop.index }}{% endfor %}")
    assert tpl.render(items="abc") == "123"


def test_loop_index0():
    tpl = Template("{% for x in items %}{{ loop.index0 }}{% endfor %}")
    assert tpl.render(items="abc") == "012"


def test_loop_first_last():
    tpl = Template(
        "{% for x in items %}"
        "{% if loop.first %}<{% endif %}{{ x }}"
        "{% if loop.last %}>{% else %},{% endif %}"
        "{% endfor %}"
    )
    assert tpl.render(items=[1, 2, 3]) == "<1,2,3>"


def test_loop_length():
    tpl = Template("{% for x in items %}{{ loop.length }}{% endfor %}")
    assert tpl.render(items=[5, 6]) == "22"


def test_loop_variable_does_not_leak():
    tpl = Template("{% for x in items %}{{ x }}{% endfor %}[{{ x }}]")
    assert tpl.render(items=[1]) == "1[]"


def test_loop_helper_does_not_leak():
    tpl = Template("{% for x in items %}{% endfor %}[{{ loop.index }}]")
    assert tpl.render(items=[1]) == "[]"


def test_nested_loops():
    tpl = Template(
        "{% for row in rows %}"
        "{% for cell in row %}{{ cell }}{% if not loop.last %},{% endif %}{% endfor %}"
        ";{% endfor %}"
    )
    assert tpl.render(rows=[[1, 2], [3, 4]]) == "1,2;3,4;"


def test_nested_loops_inner_loop_variable_shadows():
    tpl = Template(
        "{% for x in rows %}{% for x in cols %}{{ x }}{% endfor %}|{% endfor %}"
    )
    assert tpl.render(rows=[1, 2], cols=["a", "b"]) == "ab|ab|"


def test_loop_over_dict_items_via_attribute():
    tpl = Template("{% for u in users %}{{ u.name }} {% endfor %}")
    assert tpl.render(users=[{"name": "a"}, {"name": "b"}]) == "a b "


def test_loop_with_condition_inside():
    tpl = Template(
        "{% for n in nums %}{% if n > 1 %}{{ n }}{% endif %}{% endfor %}"
    )
    assert tpl.render(nums=[0, 1, 2, 3]) == "23"
