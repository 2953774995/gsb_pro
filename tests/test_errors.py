"""Syntax and reference errors must raise TplError with clear messages."""

import pytest

from tinytpl import DictLoader, Environment, Template, TplError


def test_unclosed_variable_tag():
    with pytest.raises(TplError, match="unclosed"):
        Template("hello {{ name")


def test_unclosed_statement_tag():
    with pytest.raises(TplError, match="unclosed"):
        Template("{% if x %}")


def test_unclosed_comment():
    with pytest.raises(TplError, match="unclosed"):
        Template("text {# never closed")


def test_unknown_tag():
    with pytest.raises(TplError, match="unknown tag"):
        Template("{% frobnicate %}")


def test_unexpected_endif():
    with pytest.raises(TplError, match="unexpected"):
        Template("{% endif %}")


def test_unexpected_endfor():
    with pytest.raises(TplError, match="unexpected"):
        Template("{% endfor %}")


def test_unexpected_else():
    with pytest.raises(TplError, match="unexpected"):
        Template("{% else %}")


def test_mismatched_endif_after_for():
    with pytest.raises(TplError):
        Template("{% for x in xs %}{% endif %}")


def test_mismatched_endfor_after_if():
    with pytest.raises(TplError):
        Template("{% if x %}{% endfor %}")


def test_unclosed_if():
    with pytest.raises(TplError, match="endif"):
        Template("{% if x %}never closed")


def test_unclosed_for():
    with pytest.raises(TplError, match="endfor"):
        Template("{% for x in xs %}never closed")


def test_unclosed_block():
    with pytest.raises(TplError, match="endblock"):
        Template("{% block a %}never closed")


def test_if_without_condition():
    with pytest.raises(TplError, match="condition"):
        Template("{% if %}{% endif %}")


def test_for_malformed():
    with pytest.raises(TplError, match="for"):
        Template("{% for x %}{% endfor %}")


def test_empty_output_expression():
    with pytest.raises(TplError, match="empty expression"):
        Template("{{ }}")


def test_bad_expression():
    with pytest.raises(TplError):
        Template("{{ 1 + }}")


def test_unbalanced_paren():
    with pytest.raises(TplError):
        Template("{{ (1 + 2 }}")


def test_unknown_filter():
    with pytest.raises(TplError, match="unknown filter"):
        Template("{{ x | nosuchfilter }}").render(x=1)


def test_endblock_name_mismatch():
    with pytest.raises(TplError, match="does not match"):
        Template("{% block a %}{% endblock b %}")


def test_error_message_contains_line_number():
    try:
        Template("line1\nline2\n{% bad %}")
    except TplError as exc:
        assert "line 3" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected TplError")


def test_error_message_contains_template_name():
    env = Environment(DictLoader({"bad.html": "{% unknown %}"}))
    with pytest.raises(TplError, match="bad.html"):
        env.get_template("bad.html")


def test_not_iterable_error():
    with pytest.raises(TplError, match="not iterable"):
        Template("{% for x in n %}{% endfor %}").render(n=5)


def test_comment_is_removed():
    assert Template("a{# comment #}b").render() == "ab"


def test_comment_with_tags_inside():
    assert Template("a{# {{ x }} {% if %} #}b").render() == "ab"
