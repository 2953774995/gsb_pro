import pytest

from mdsite.markdown import render_inline, render_markdown, slugify, split_table_row


def test_all_heading_levels_and_ids():
    text = "\n".join(f"{'#' * level} 标题 {level}" for level in range(1, 7))
    html, _ = render_markdown(text)
    for level in range(1, 7):
        expected_id = f"标题-{level}"
        assert f'<h{level} id="{expected_id}">标题 {level}</h{level}>' in html


def test_paragraph_bold_italic_and_inline_code():
    html, _ = render_markdown("普通 **粗体** *斜体* `x * y`")
    assert html == "<p>普通 <strong>粗体</strong> <em>斜体</em> <code>x * y</code></p>"


def test_fenced_code_escapes_special_chars_and_skips_inline_parsing():
    markdown = "```python\nprint('<b>&</b> **not bold**')\n```"
    html, _ = render_markdown(markdown)
    assert html.startswith('<pre><code class="language-python">')
    assert "&lt;b&gt;&amp;&lt;/b&gt; **not bold**" in html
    assert "<strong>" not in html
    assert '<span class="hl-builtin">print</span>' in html


def test_unclosed_fenced_code_is_literal_until_eof():
    html, _ = render_markdown("```\n<div>\n**text**")
    assert "&lt;div&gt;" in html
    assert "**text**" in html
    assert "<strong>" not in html


def test_blockquote_supports_blocks_inline():
    html, _ = render_markdown("> 引用 **bold**\n>\n> 1. one\n> 2. two")
    assert "<blockquote>" in html
    assert "<strong>bold</strong>" in html
    assert "<ol>" in html


@pytest.mark.parametrize("indent", ["  ", "    "])
def test_nested_lists_two_levels_regular_indent(indent):
    html, _ = render_markdown(f"- parent\n{indent}- child\n- next")
    assert "<ul><li>parent<ul><li>child</li></ul></li><li>next</li></ul>" in html


def test_nested_lists_mixed_two_and_four_space_indent():
    markdown = "- a\n  - b\n    - c\n- d"
    html, _ = render_markdown(markdown)
    assert html == (
        "<ul><li>a<ul><li>b<ul><li>c</li></ul></li></ul></li>"
        "<li>d</li></ul>"
    )



def test_nested_list_child_indent_can_decrease_after_first_item():
    # 第一个子项 4 空格、后续子项 2 空格时，也都属于同一个父级列表。
    html, _ = render_markdown("- a\n    - b\n  - d\n- e")
    assert html == "<ul><li>a<ul><li>b</li><li>d</li></ul></li><li>e</li></ul>"

def test_ordered_and_unordered_nested_list_and_blank_lines():
    html, _ = render_markdown("1. one\n  - a\n\n2. two")
    assert html.startswith("<ol>")
    assert "<li>one<ul><li>a</li></ul></li>" in html
    assert "<li>two</li>" in html


def test_links_and_images_edge_cases():
    html = render_inline('[空]() and [x](https://example.com/a-(b)?x=1)')
    assert '<a data-md-link href="">空</a>' in html
    assert 'href="https://example.com/a-(b)?x=1"' in html

    image = render_inline('![](a%20b.png) ![alt](img.png)')
    assert '<img src="a%20b.png" alt="">' in image
    assert '<img src="img.png" alt="alt">' in image


def test_horizontal_rule_and_table_and_escaped_pipe():
    markdown = """
| a | b \\| c |
| :-- | --: |
| 1 | **2** |
"""
    html, _ = render_markdown(markdown)
    assert "<table>" in html
    assert '<th align="left">a</th>' in html
    assert '<th align="right">b | c</th>' in html
    assert "<strong>2</strong>" in html

    hr, _ = render_markdown("---")
    assert hr == "<hr>"


def test_split_table_row_preserves_trailing_escaped_pipe():
    assert split_table_row(r"| a | b \|") == ["a", "b |"]


def test_inline_html_is_passthrough_but_normal_angle_brackets_escape():
    html = render_inline('<span title="a > b">x</span> 1 < 2 && a &amp; b')
    assert '<span title="a > b">x</span>' in html
    assert "1 &lt; 2" in html
    assert "&amp;&amp;" in html
    assert "&amp; b" in html


def test_block_html_is_verbatim():
    markdown = '<div class="box">\n**not parsed** <span>x</span>\n</div>\nparagraph'
    html, _ = render_markdown(markdown)
    assert '<div class="box">\n**not parsed** <span>x</span>\n</div>' in html
    assert "<p>paragraph</p>" in html


def test_slugify_chinese_punctuation_and_duplicates():
    assert slugify("Hello, World!") == "hello-world"
    assert slugify("中文 标题！") == "中文-标题"
    _, toc = render_markdown("## 安装\n## 安装")
    assert [item[2] for item in toc] == ["安装", "安装-1"]


def test_link_label_with_nested_square_brackets_and_inline_markup():
    html = render_inline("[a [b] **c**](page.md)")
    assert html.startswith('<a data-md-link href="page.md">a [b] <strong>c</strong></a>')
