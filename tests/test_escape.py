"""HTML escaping and the raw filter."""

from tinytpl import Template


def test_html_special_chars_escaped():
    tpl = Template("{{ x }}")
    out = tpl.render(x="<b>&\"'</b>")
    assert out == "&lt;b&gt;&amp;&quot;&#x27;&lt;/b&gt;"


def test_each_special_char():
    tpl = Template("{{ x }}")
    assert tpl.render(x="<") == "&lt;"
    assert tpl.render(x=">") == "&gt;"
    assert tpl.render(x="&") == "&amp;"
    assert tpl.render(x='"') == "&quot;"
    assert tpl.render(x="'") == "&#x27;"


def test_raw_filter_skips_escaping():
    tpl = Template("{{ x | raw }}")
    assert tpl.render(x="<b>bold</b>") == "<b>bold</b>"


def test_raw_filter_no_spaces():
    tpl = Template("{{ x|raw }}")
    assert tpl.render(x="<i>x</i>") == "<i>x</i>"


def test_escape_filter_explicit():
    tpl = Template("{{ x | escape }}")
    assert tpl.render(x="<b>") == "&lt;b&gt;"


def test_plain_text_not_escaped():
    assert Template("a < b {% if ok %}& c{% endif %}").render(ok=True) == "a < b & c"


def test_safe_string_not_double_escaped():
    tpl = Template("{{ x | escape }}")
    assert tpl.render(x="&") == "&amp;"


def test_upper_lower_filters():
    assert Template("{{ s | upper }}").render(s="abc") == "ABC"
    assert Template("{{ s | lower }}").render(s="ABC") == "abc"


def test_length_filter():
    assert Template("{{ xs | length }}").render(xs=[1, 2, 3]) == "3"
