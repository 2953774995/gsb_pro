"""TOC 提取与锚点 slug 的测试。"""
import re

from mdsite.markdown import Slugger, render_page, slugify


def test_slugify_basic():
    assert slugify("Hello World") == "hello-world"


def test_slugify_strips_punctuation():
    assert slugify("Section 2.1: What's new?") == "section-21-whats-new"


def test_slugify_chinese_stable():
    # 中文标题生成稳定锚点（中文字符保留，可重复调用结果一致）
    s1 = slugify("快速开始")
    s2 = slugify("快速开始")
    assert s1 == s2 == "快速开始"


def test_slugify_mixed_chinese_english():
    assert slugify("第二章 安装指南") == "第二章-安装指南"


def test_slugify_fallback():
    assert slugify("!!!") == "section"


def test_toc_only_h2_h3():
    md = "# 一\n\n## 二\n\n### 三\n\n#### 四\n"
    _, toc, _ = render_page(md)
    levels = [level for level, _, _ in toc]
    assert levels == [2, 3]


def test_toc_anchors_match_heading_ids():
    md = "## 快速开始\n\n### 第一步 Install\n\n## 快速开始\n"
    html, toc, _ = render_page(md)
    ids_in_html = re.findall(r'<h[23] id="([^"]+)"', html)
    anchors_in_toc = [anchor for _, anchor, _ in toc]
    # TOC 里的每个锚点都必须能在页面里找到对应的 id
    assert anchors_in_toc == ids_in_html
    # 重复标题的锚点要唯一
    assert len(set(ids_in_html)) == len(ids_in_html)


def test_toc_text_is_plain():
    md = "## 带 **粗体** 和 `代码` 的标题\n"
    _, toc, _ = render_page(md)
    assert toc[0][2] == "带 粗体 和 代码 的标题"


def test_slugger_dedup():
    s = Slugger()
    assert s.slug("重复") == "重复"
    assert s.slug("重复") == "重复-1"
    assert s.slug("重复") == "重复-2"
