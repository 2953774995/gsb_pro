"""Markdown 解析器的单元测试：每种语法元素逐一覆盖。"""
import pytest

from mdsite.markdown import render_html, render_page


# ---------------------------------------------------------------------------
# 标题
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("level", range(1, 7))
def test_heading_levels(level):
    md = "#" * level + " 标题"
    html = render_html(md)
    assert html == '<h%d id="标题">标题</h%d>' % (level, level)


def test_heading_requires_space():
    # `#tag` 不是标题，应当作普通段落
    assert render_html("#tag") == "<p>#tag</p>"


def test_heading_closing_hashes_stripped():
    assert "<h2" in render_html("## 标题 ##")


# ---------------------------------------------------------------------------
# 段落与行内元素
# ---------------------------------------------------------------------------

def test_paragraph():
    assert render_html("你好，世界") == "<p>你好，世界</p>"


def test_paragraphs_split_by_blank_line():
    html = render_html("第一段\n\n第二段")
    assert html == "<p>第一段</p>\n<p>第二段</p>"


def test_bold():
    assert "<strong>加粗</strong>" in render_html("这是 **加粗** 文本")


def test_italic():
    assert "<em>斜体</em>" in render_html("这是 *斜体* 文本")


def test_inline_code():
    assert "<code>x = 1</code>" in render_html("运行 `x = 1` 即可")


def test_inline_code_escapes_html():
    assert "<code>&lt;b&gt;</code>" in render_html("`<b>`")


def test_plain_text_is_escaped():
    html = render_html("1 < 2 & 3 > 2")
    assert "1 &lt; 2 &amp; 3 &gt; 2" in html


def test_inline_html_passthrough():
    html = render_html("这是 <span class=\"x\">行内</span> HTML")
    assert '<span class="x">行内</span>' in html


# ---------------------------------------------------------------------------
# 代码块
# ---------------------------------------------------------------------------

def test_code_block_with_language():
    html = render_html("```python\nprint(1)\n```")
    assert '<pre><code class="language-python">' in html


def test_code_block_escapes_special_chars():
    html = render_html("```\nif a < b && c > d:\n```")
    assert "&lt;" in html and "&gt;" in html and "&amp;&amp;" in html
    assert "<b>" not in html


def test_code_block_no_inline_parsing():
    # 代码块里的 ** ` 等标记必须按字面量输出
    html = render_html("```\n**not bold** `not code`\n```")
    assert "<strong>" not in html
    assert "**not bold**" in html
    assert "`not code`" in html


def test_code_block_unclosed_fence():
    # 没有收尾的 ``` 不应崩溃
    html = render_html("```python\nx = 1")
    assert "x = " in html
    assert "<pre><code" in html


def test_python_highlight_keywords():
    html = render_html("```python\ndef f():\n    return \"s\"  # hi\n```")
    assert '<span class="tok-k">def</span>' in html
    assert '<span class="tok-s">&quot;' not in html  # 字符串整体着色
    assert '<span class="tok-s">' in html
    assert '<span class="tok-c"># hi</span>' in html


# ---------------------------------------------------------------------------
# 引用块 / 水平线
# ---------------------------------------------------------------------------

def test_blockquote():
    html = render_html("> 引用内容")
    assert html == "<blockquote><p>引用内容</p></blockquote>"


def test_blockquote_multiline_with_inline():
    html = render_html("> 第一行 **粗体**\n> 第二行")
    assert "<blockquote>" in html and "<strong>粗体</strong>" in html


def test_horizontal_rule():
    assert render_html("---") == "<hr>"
    assert render_html("***") == "<hr>"


# ---------------------------------------------------------------------------
# 列表
# ---------------------------------------------------------------------------

def test_unordered_list():
    html = render_html("- 甲\n- 乙")
    assert html == "<ul><li>甲</li><li>乙</li></ul>"


def test_ordered_list():
    html = render_html("1. 第一\n2. 第二")
    assert html == "<ol><li>第一</li><li>第二</li></ol>"


def test_nested_list_two_levels():
    html = render_html("- 外\n  - 内一\n  - 内二\n- 外二")
    assert "<ul><li>外<ul><li>内一</li><li>内二</li></ul></li><li>外二</li></ul>" == html


def test_nested_list_mixed_indent_does_not_crash():
    # 2 空格和 4 空格混用
    html = render_html("- a\n  - b\n    - c\n  - d\n- e")
    assert html.count("<li>") == 5
    assert html.count("<ul>") == 3


def test_nested_ordered_in_unordered():
    html = render_html("- 外\n  1. 一\n  2. 二")
    assert "<ol><li>一</li><li>二</li></ol>" in html


def test_list_inline_markup():
    html = render_html("- **粗** 和 `码`")
    assert "<strong>粗</strong>" in html and "<code>码</code>" in html


# ---------------------------------------------------------------------------
# 链接与图片
# ---------------------------------------------------------------------------

def test_link():
    html = render_html("[文档](https://example.com)")
    assert '<a href="https://example.com">文档</a>' in html


def test_link_empty_text():
    html = render_html("[](https://example.com)")
    assert '<a href="https://example.com"></a>' in html


def test_link_empty_url():
    html = render_html("[文本]()")
    assert '<a href="">文本</a>' in html


def test_link_nested_parens_in_url():
    html = render_html("[wiki](https://zh.wikipedia.org/wiki/测试_(消歧义))")
    assert '<a href="https://zh.wikipedia.org/wiki/测试_(消歧义)">wiki</a>' in html


def test_link_text_with_markup():
    html = render_html("[**粗体**链接](http://x)")
    assert '<a href="http://x"><strong>粗体</strong>链接</a>' in html


def test_image():
    html = render_html("![示意图](img/a.png)")
    assert '<img src="img/a.png" alt="示意图">' in html


def test_image_empty_alt():
    html = render_html("![](img/a.png)")
    assert '<img src="img/a.png" alt="">' in html


def test_image_alt_with_markup_is_plain():
    html = render_html("![**星**图](a.png)")
    assert 'alt="星图"' in html


# ---------------------------------------------------------------------------
# 表格
# ---------------------------------------------------------------------------

def test_table_basic():
    md = "| 名称 | 类型 |\n| --- | --- |\n| a | int |\n| b | str |"
    html = render_html(md)
    assert "<table>" in html
    assert "<th>名称</th>" in html and "<th>类型</th>" in html
    assert "<td>a</td>" in html and "<td>str</td>" in html


def test_table_without_outer_pipes():
    md = "名称 | 类型\n--- | ---\na | int"
    html = render_html(md)
    assert "<th>名称</th>" in html and "<td>int</td>" in html


def test_table_escaped_pipe():
    md = "| 表达式 | 含义 |\n| --- | --- |\n| a \\| b | 或 |"
    html = render_html(md)
    assert "<td>a | b</td>" in html
    assert "<td>或</td>" in html
    # 转义的竖线不应把单元格拆开
    assert html.count("<td>") == 2


def test_table_row_column_mismatch_padded():
    md = "| a | b | c |\n| --- | --- | --- |\n| 1 | 2 |"
    html = render_html(md)
    assert html.count("<td>") == 3


def test_table_inline_markup_in_cells():
    md = "| k |\n| --- |\n| **v** |"
    assert "<td><strong>v</strong></td>" in render_html(md)


# ---------------------------------------------------------------------------
# 块级 HTML
# ---------------------------------------------------------------------------

def test_block_html_passthrough():
    md = '<div class="note">\n原始 <b>HTML</b>\n</div>'
    html = render_html(md)
    assert '<div class="note">' in html
    assert "原始 <b>HTML</b>" in html
    assert "<p>" not in html


# ---------------------------------------------------------------------------
# 综合：render_page 返回值
# ---------------------------------------------------------------------------

def test_render_page_returns_title_from_first_h1():
    _, _, title = render_page("# 文档标题\n\n## 小节")
    assert title == "文档标题"


def test_render_page_no_h1_title_is_none():
    _, _, title = render_page("## 只有二级")
    assert title is None
