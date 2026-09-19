"""for 循环、loop 变量、嵌套循环。"""

from tinytpl import Template


def test_basic_for():
    tpl = Template("{% for x in items %}{{ x }},{% endfor %}")
    assert tpl.render(items=[1, 2, 3]) == "1,2,3,"


def test_for_over_dict_keys():
    tpl = Template("{% for k in d %}{{ k }} {% endfor %}")
    assert tpl.render(d={"a": 1, "b": 2}) == "a b "


def test_loop_index_first_last():
    tpl = Template(
        "{% for x in items %}"
        "{{ loop.index }}:{{ loop.first }}:{{ loop.last }};"
        "{% endfor %}")
    assert tpl.render(items=["a", "b", "c"]) \
        == "1:True:False;2:False:False;3:False:True;"


def test_loop_index0_and_length():
    tpl = Template(
        "{% for x in items %}{{ loop.index0 }}/{{ loop.length }} {% endfor %}")
    assert tpl.render(items=["a", "b"]) == "0/2 1/2 "


def test_empty_iterable():
    tpl = Template("[{% for x in items %}x{% endfor %}]")
    assert tpl.render(items=[]) == "[]"


def test_for_over_missing_variable_is_empty():
    tpl = Template("[{% for x in missing %}x{% endfor %}]")
    assert tpl.render() == "[]"


def test_nested_loops():
    tpl = Template(
        "{% for row in matrix %}"
        "{% for cell in row %}{{ cell }}{% endfor %};"
        "{% endfor %}")
    assert tpl.render(matrix=[[1, 2], [3, 4]]) == "12;34;"


def test_nested_loops_with_loop_vars():
    tpl = Template(
        "{% for row in matrix %}"
        "{% for cell in row %}{{ loop.index }}{% endfor %}"
        "outer={{ loop.index }};"
        "{% endfor %}")
    assert tpl.render(matrix=[["a", "b"], ["c", "d"]]) == "12outer=1;12outer=2;"


def test_loop_with_dot_access():
    tpl = Template("{% for u in users %}{{ u.name }} {% endfor %}")
    assert tpl.render(users=[{"name": "a"}, {"name": "b"}]) == "a b "


def test_for_with_if_inside():
    tpl = Template(
        "{% for n in nums %}{% if n % 2 == 0 %}{{ n }}{% endif %}{% endfor %}")
    assert tpl.render(nums=[1, 2, 3, 4]) == "24"
