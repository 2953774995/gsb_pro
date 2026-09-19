"""各类语法错误与引用错误都必须抛 TplError。"""

import pytest

from tinytpl import DictLoader, Environment, Template, TplError


def test_unclosed_variable_tag():
    with pytest.raises(TplError, match="unclosed"):
        Template("hello {{ name")


def test_unclosed_statement_tag():
    with pytest.raises(TplError, match="unclosed"):
        Template("{% if x")


def test_unclosed_comment():
    with pytest.raises(TplError, match="unclosed"):
        Template("{# never ends")


def test_unknown_tag():
    with pytest.raises(TplError, match="unknown tag 'foo'"):
        Template("{% foo %}")


def test_unexpected_endif():
    with pytest.raises(TplError, match="unexpected tag 'endif'"):
        Template("{% endif %}")


def test_unexpected_endfor():
    with pytest.raises(TplError, match="unexpected tag 'endfor'"):
        Template("{% endfor %}")


def test_unexpected_else():
    with pytest.raises(TplError, match="unexpected tag 'else'"):
        Template("{% else %}")


def test_if_without_endif():
    with pytest.raises(TplError, match="expected"):
        Template("{% if x %}open")


def test_for_without_endfor():
    with pytest.raises(TplError, match="endfor"):
        Template("{% for x in items %}open")


def test_block_without_endblock():
    with pytest.raises(TplError, match="endblock"):
        Template("{% block b %}open")


def test_mismatched_end_tags():
    # if 里遇到 endfor：endfor 不是 if 的结束标签
    with pytest.raises(TplError):
        Template("{% if x %}{% endfor %}{% endif %}")


def test_malformed_for():
    with pytest.raises(TplError, match="malformed for"):
        Template("{% for x items %}{% endfor %}")


def test_malformed_block():
    with pytest.raises(TplError, match="malformed block"):
        Template("{% block %}{% endblock %}")


def test_bad_expression():
    with pytest.raises(TplError):
        Template("{{ 1 + }}")


def test_empty_expression():
    with pytest.raises(TplError, match="empty expression"):
        Template("{{ }}")


def test_unbalanced_paren():
    with pytest.raises(TplError):
        Template("{{ (1 + 2 }}")


def test_unknown_filter():
    with pytest.raises(TplError, match="unknown filter"):
        Template("{{ x | upper }}")


def test_error_message_contains_line_number():
    try:
        Template("line1\nline2\n{{ 1 + }}")
    except TplError as exc:
        assert "line 3" in str(exc)
    else:  # pragma: no cover
        pytest.fail("expected TplError")


def test_template_not_found():
    env = Environment(DictLoader({}))
    with pytest.raises(TplError, match="template not found"):
        env.get_template("missing.html")


def test_endif_with_arguments():
    with pytest.raises(TplError, match="no arguments"):
        Template("{% if x %}{% endif x %}")


def test_else_with_arguments():
    with pytest.raises(TplError, match="no arguments"):
        Template("{% if x %}{% else y %}{% endif %}")


def test_comment_is_ignored():
    assert Template("a{# comment {{ x }} {% if %} #}b").render() == "ab"
