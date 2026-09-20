from mdsite.highlight import highlight_code


def test_python_highlights_common_tokens_and_escapes():
    code = "# comment\nname = 'mdsite'\nvalue = 42\n"
    html = highlight_code(code, "python")
    assert '<span class="hl-comment"># comment</span>' in html
    assert '<span class="hl-str">&#x27;mdsite&#x27;</span>' in html
    assert '<span class="hl-num">42</span>' in html
    assert "&#x27;" in html  # html.escape 会转义单引号


def test_hash_inside_python_string_is_not_comment():
    html = highlight_code('value = "# not comment"', "python")
    assert "hl-comment" not in html
    assert '<span class="hl-str">' in html


def test_unknown_language_still_escapes():
    html = highlight_code("< > &", "definitely-unknown")
    assert html == "&lt; &gt; &amp;"
