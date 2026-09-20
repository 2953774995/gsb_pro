"""代码高亮器的测试。"""
from mdsite.highlight import highlight_code


def test_python_keywords_colored():
    html = highlight_code("def f():\n    return None", "python")
    assert '<span class="tok-k">def</span>' in html
    assert '<span class="tok-k">return</span>' in html
    assert '<span class="tok-k">None</span>' in html


def test_python_string_and_comment():
    html = highlight_code('x = "hi"  # 注释', "py")
    assert '<span class="tok-s">&quot;' not in html
    assert '<span class="tok-s">"hi"</span>' in html
    assert '<span class="tok-c"># 注释</span>' in html


def test_html_special_chars_escaped():
    html = highlight_code("if a < b && c > d:", "python")
    assert "&lt;" in html and "&gt;" in html and "&amp;&amp;" in html
    assert "<b>" not in html.replace("<span", "").replace("<pre", "").replace("<code", "")


def test_unknown_language_passthrough_escaped():
    html = highlight_code("<tag>", "brainfuck")
    assert 'class="language-brainfuck"' in html
    assert "&lt;tag&gt;" in html
    assert "<span" not in html


def test_no_language():
    html = highlight_code("plain")
    assert html == "<pre><code>plain</code></pre>"


def test_language_in_class_attr():
    html = highlight_code("x", "Python")  # 大小写不敏感
    assert 'class="language-python"' in html
