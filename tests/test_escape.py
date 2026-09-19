"""HTML 转义与 raw 过滤器。"""

from tinytpl import Template


def test_html_special_chars_escaped():
    out = Template("{{ v }}").render(v="<b>&\"'</b>")
    assert out == "&lt;b&gt;&amp;&quot;&#x27;&lt;/b&gt;"


def test_all_five_chars():
    out = Template("{{ v }}").render(v="<>&\"'")
    assert "&lt;" in out and "&gt;" in out and "&amp;" in out
    assert "&quot;" in out and "&#x27;" in out


def test_raw_filter_skips_escaping():
    assert Template("{{ v | raw }}").render(v="<b>hi</b>") == "<b>hi</b>"


def test_raw_filter_with_spaces():
    assert Template("{{ v|raw }}").render(v="<i>") == "<i>"


def test_normal_output_still_escaped_when_raw_elsewhere():
    tpl = Template("{{ a | raw }}|{{ b }}")
    assert tpl.render(a="<x>", b="<y>") == "<x>|&lt;y&gt;"


def test_numbers_render_untouched():
    assert Template("{{ n }}").render(n=3.5) == "3.5"
