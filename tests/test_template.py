import pytest

from mdsite.template import TemplateError, render_template


def test_variables_and_dotted_lookup():
    output = render_template(
        "{{ title }} - {{ page.name }}",
        {"title": "Hi", "page": {"name": "Guide"}},
    )
    assert output == "Hi - Guide"


def test_if_else_and_not():
    template = "{% if show %}yes{% else %}no{% endif %}/{% if not hidden %}ok{% endif %}"
    assert render_template(template, {"show": False, "hidden": False}) == "no/ok"


def test_for_loop_with_dict_items():
    template = "{% for item in items %}[{{ item.text }}]{% endfor %}"
    context = {"items": [{"text": "a"}, {"text": "b"}]}
    assert render_template(template, context) == "[a][b]"


def test_missing_variable_is_an_error():
    with pytest.raises(TemplateError):
        render_template("{{ missing }}", {})


def test_unclosed_block_is_an_error():
    with pytest.raises(TemplateError):
        render_template("{% if x %}", {"x": True})
