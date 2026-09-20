"""端到端构建测试：临时目录造文档，build 后检查输出。"""
import os
import re

import pytest

from mdsite.builder import build
from mdsite.errors import MdsiteError


INDEX_MD = """# 首页

## 项目介绍

欢迎使用 **mdsite**，详见 [上手指南](guide/start.html)。

## 快速开始

```python
import mdsite
```
"""

START_MD = """# 上手指南

## 安装

### 环境要求

- Python 3
  - 3.8 及以上

## 配置

| 键 | 说明 |
| --- | --- |
| theme | 主题 \\| 外观 |

---

> 提示：先看安装。
"""

API_MD = """# API 参考

## build 函数

`build(src, dst)` 构建站点。

## serve 函数

本地预览。
"""


@pytest.fixture
def site(tmp_path):
    """造一个三篇文档（含子目录）的输入站点。"""
    src = tmp_path / "docs"
    (src / "guide").mkdir(parents=True)
    (src / "api").mkdir()
    (src / "index.md").write_text(INDEX_MD, encoding="utf-8")
    (src / "guide" / "start.md").write_text(START_MD, encoding="utf-8")
    (src / "api" / "ref.md").write_text(API_MD, encoding="utf-8")
    dst = tmp_path / "out"
    count = build(str(src), str(dst))
    return src, dst, count


def test_build_page_count(site):
    assert site[2] == 3


def test_output_structure(site):
    _, dst, _ = site
    assert (dst / "index.html").is_file()
    assert (dst / "guide" / "start.html").is_file()
    assert (dst / "api" / "ref.html").is_file()
    assert (dst / "assets" / "style.css").is_file()


def test_no_leftover_placeholders(site):
    _, dst, _ = site
    for html_file in dst.rglob("*.html"):
        text = html_file.read_text(encoding="utf-8")
        assert "{{" not in text, "模板占位符残留: %s" % html_file
        assert "{%" not in text


def test_toc_links_resolve_to_heading_ids(site):
    _, dst, _ = site
    html = (dst / "guide" / "start.html").read_text(encoding="utf-8")
    heading_ids = set(re.findall(r'<h[23] id="([^"]+)"', html))
    toc_hrefs = re.findall(r'<nav class="toc">.*?href="#([^"]+)"', html, re.S)
    assert toc_hrefs, "TOC 为空"
    for href in toc_hrefs:
        assert href in heading_ids, "TOC 锚点 #%s 没有对应的标题 id" % href


def test_toc_excludes_h1_and_h4(site):
    _, dst, _ = site
    html = (dst / "guide" / "start.html").read_text(encoding="utf-8")
    toc = re.search(r'<nav class="toc">.*?</nav>', html, re.S).group(0)
    assert "上手指南" not in toc  # h1 不进 TOC
    assert "安装" in toc and "环境要求" in toc and "配置" in toc


def test_content_rendered(site):
    _, dst, _ = site
    html = (dst / "guide" / "start.html").read_text(encoding="utf-8")
    assert "<table>" in html          # 表格
    assert "<td>theme</td>" in html
    assert "<hr>" in html             # 水平线
    assert "<blockquote>" in html     # 引用
    assert "<ul><li>Python 3" in html.replace("\n", "") or "<li>Python 3" in html  # 列表
    index = (dst / "index.html").read_text(encoding="utf-8")
    assert "<strong>mdsite</strong>" in index
    assert 'class="language-python"' in index  # 代码块语言标注
    assert '<a href="guide/start.html">上手指南</a>' in index


def test_nav_present_and_active(site):
    _, dst, _ = site
    html = (dst / "guide" / "start.html").read_text(encoding="utf-8")
    assert '<nav class="nav">' in html
    assert '<li class="active"><a href="../guide/start.html">上手指南</a></li>' in html
    # 相对路径回到根
    assert 'href="../index.html"' in html


def test_relative_css_path(site):
    _, dst, _ = site
    top = (dst / "index.html").read_text(encoding="utf-8")
    nested = (dst / "guide" / "start.html").read_text(encoding="utf-8")
    assert 'href="./assets/style.css"' in top
    assert 'href="../assets/style.css"' in nested


def test_title_from_h1(site):
    _, dst, _ = site
    html = (dst / "api" / "ref.html").read_text(encoding="utf-8")
    assert "<title>API 参考</title>" in html


def test_theme_switch(tmp_path):
    src = tmp_path / "docs"
    src.mkdir()
    (src / "index.md").write_text("# t\n\n## s\n", encoding="utf-8")
    for theme in ("default", "dark"):
        dst = tmp_path / ("out-" + theme)
        build(str(src), str(dst), theme=theme)
        html = (dst / "index.html").read_text(encoding="utf-8")
        assert 'data-theme="%s"' % theme in html
    default_css = (tmp_path / "out-default" / "assets" / "style.css").read_text()
    dark_css = (tmp_path / "out-dark" / "assets" / "style.css").read_text()
    assert default_css != dark_css


# ---------------------------------------------------------------------------
# 非法输入：必须给明确报错（MdsiteError），不能 traceback
# ---------------------------------------------------------------------------

def test_src_not_exists(tmp_path):
    with pytest.raises(MdsiteError, match="不存在"):
        build(str(tmp_path / "nope"), str(tmp_path / "out"))


def test_src_not_a_directory(tmp_path):
    f = tmp_path / "file.md"
    f.write_text("# x", encoding="utf-8")
    with pytest.raises(MdsiteError, match="不是目录"):
        build(str(f), str(tmp_path / "out"))


def test_no_markdown_files(tmp_path):
    src = tmp_path / "empty"
    src.mkdir()
    with pytest.raises(MdsiteError, match="没有 .md"):
        build(str(src), str(tmp_path / "out"))


def test_unknown_theme(tmp_path):
    src = tmp_path / "docs"
    src.mkdir()
    (src / "a.md").write_text("# a", encoding="utf-8")
    with pytest.raises(MdsiteError, match="未知主题"):
        build(str(src), str(tmp_path / "out"), theme="bogus")


def test_unreadable_file(tmp_path):
    src = tmp_path / "docs"
    src.mkdir()
    f = src / "secret.md"
    f.write_text("# x", encoding="utf-8")
    os.chmod(str(f), 0)
    try:
        with pytest.raises(MdsiteError, match="无法读取"):
            build(str(src), str(tmp_path / "out"))
    finally:
        os.chmod(str(f), 0o644)


def test_invalid_utf8_file(tmp_path):
    src = tmp_path / "docs"
    src.mkdir()
    (src / "bad.md").write_bytes(b"\xff\xfe invalid \x00")
    with pytest.raises(MdsiteError, match="UTF-8"):
        build(str(src), str(tmp_path / "out"))


def test_dst_exists_as_file(tmp_path):
    src = tmp_path / "docs"
    src.mkdir()
    (src / "a.md").write_text("# a", encoding="utf-8")
    dst = tmp_path / "out"
    dst.write_text("i am a file", encoding="utf-8")
    with pytest.raises(MdsiteError, match="不是目录"):
        build(str(src), str(dst))
