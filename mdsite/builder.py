"""站点构建：扫描 Markdown -> 渲染 -> 套模板 -> 拷贝主题资源。"""
from __future__ import annotations

import html as _html
import os
import shutil

from . import markdown as md
from . import template as tpl
from .errors import MdsiteError

THEMES = ("default", "dark")

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_TEMPLATE_PATH = os.path.join(_PKG_DIR, "templates", "page.html")


def _theme_path(theme: str) -> str:
    return os.path.join(_PKG_DIR, "themes", "%s.css" % theme)


def _esc(text: str) -> str:
    return _html.escape(text, quote=True)


def _posix(path: str) -> str:
    return path.replace(os.sep, "/")


def _render_toc(toc) -> str:
    if not toc:
        return ""
    items = "".join(
        '<li class="toc-h%d"><a href="#%s">%s</a></li>' % (level, hid, _esc(text))
        for level, hid, text in toc
    )
    return '<nav class="toc"><div class="toc-title">目录</div><ul>%s</ul></nav>' % items


def _render_nav(pages, current_rel, root) -> str:
    items = []
    for rel, title in pages:
        href = _posix(os.path.join(root, rel)) if root != "." else _posix(rel)
        cls = ' class="active"' if rel == current_rel else ""
        items.append('<li%s><a href="%s">%s</a></li>' % (cls, _esc(href), _esc(title)))
    return "<ul>%s</ul>" % "".join(items)


def _find_markdown_files(src):
    found = []
    for root, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if name.lower().endswith(".md"):
                found.append(os.path.join(root, name))
    return sorted(found)


def build(src, dst, theme="default"):
    """构建站点，返回生成的页面数。用户级错误抛 MdsiteError。"""
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)
    if not os.path.exists(src):
        raise MdsiteError("输入目录不存在: %s" % src)
    if not os.path.isdir(src):
        raise MdsiteError("输入路径不是目录: %s" % src)
    if theme not in THEMES:
        raise MdsiteError("未知主题: %s（可选: %s）" % (theme, ", ".join(THEMES)))
    if os.path.exists(dst) and not os.path.isdir(dst):
        raise MdsiteError("输出路径已存在且不是目录: %s" % dst)

    md_files = _find_markdown_files(src)
    if not md_files:
        raise MdsiteError("输入目录里没有 .md 文件: %s" % src)

    # 第一遍：解析所有页面（拿到标题用于导航）
    parsed = []  # (out_rel, content, toc, title)
    for path in md_files:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            raise MdsiteError("无法读取文件 %s: %s" % (path, e.strerror or e)) from e
        except UnicodeDecodeError as e:
            raise MdsiteError("文件不是有效的 UTF-8 文本 %s: %s" % (path, e)) from e
        rel = os.path.relpath(path, src)
        out_rel = os.path.splitext(rel)[0] + ".html"
        content, toc, title = md.render_page(text)
        if not title:
            title = os.path.splitext(os.path.basename(rel))[0]
        parsed.append((out_rel, content, toc, title))

    pages = [(out_rel, title) for out_rel, _, _, title in parsed]

    try:
        with open(_TEMPLATE_PATH, "r", encoding="utf-8") as fh:
            page_tpl = fh.read()
    except OSError as e:
        raise MdsiteError("无法读取页面模板 %s: %s" % (_TEMPLATE_PATH, e)) from e

    # 第二遍：套模板写出
    os.makedirs(dst, exist_ok=True)
    for out_rel, content, toc, title in parsed:
        out_path = os.path.join(dst, out_rel)
        parent = os.path.dirname(out_path)
        root = os.path.relpath(dst, parent) if parent != dst else "."
        page_html = tpl.render(
            page_tpl,
            {
                "title": _esc(title),
                "content": content,
                "toc": _render_toc(toc),
                "nav": _render_nav(pages, out_rel, root),
                "root": _posix(root),
                "theme": theme,
            },
        )
        os.makedirs(parent, exist_ok=True)
        try:
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(page_html)
        except OSError as e:
            raise MdsiteError("无法写入文件 %s: %s" % (out_path, e.strerror or e)) from e

    # 拷贝主题 CSS
    assets_dir = os.path.join(dst, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    try:
        shutil.copyfile(_theme_path(theme), os.path.join(assets_dir, "style.css"))
    except OSError as e:
        raise MdsiteError("拷贝主题文件失败: %s" % e) from e

    return len(parsed)
