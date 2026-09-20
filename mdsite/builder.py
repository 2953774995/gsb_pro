"""站点构建：扫描 Markdown，渲染页面，复制资源和主题。"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import List, Tuple
import html as _html

from .markdown import _plain_text, escape, render_markdown
from .template import TemplateError, render_template

_PACKAGE_DIR = Path(__file__).resolve().parent


class MdsiteError(Exception):
    """可直接展示给用户的错误；CLI 不打印 traceback。"""


def available_themes() -> List[str]:
    return sorted(path.stem for path in (_PACKAGE_DIR / "themes").glob("*.css"))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise MdsiteError(f"文件不是有效的 UTF-8 文本: {path}") from None
    except OSError as exc:
        raise MdsiteError(f"无法读取文件 {path}: {exc.strerror or exc}") from None


def _write_text(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise MdsiteError(f"无法写入文件 {path}: {exc.strerror or exc}") from None


def _copy_file(source: Path, target: Path) -> None:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    except (OSError, shutil.Error) as exc:
        raise MdsiteError(f"无法复制文件 {source} -> {target}: {exc}") from None


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _walk_files(root: Path, excluded_paths=None) -> List[Path]:
    """收集所有普通文件；遇到权限等错误时转换成友好异常。"""
    excluded_paths = set(excluded_paths or ())
    files: List[Path] = []

    def on_error(exc: OSError) -> None:
        raise MdsiteError(f"无法扫描目录 {root}: {exc.strerror or exc}")

    try:
        for dirpath, dirnames, filenames in os.walk(root, onerror=on_error):
            current = Path(dirpath).resolve()
            dirnames[:] = [
                name for name in dirnames
                if (current / name).resolve() not in excluded_paths
            ]
            dirnames.sort()
            for filename in sorted(filenames):
                path = Path(dirpath) / filename
                try:
                    if path.is_file() and not any(
                        part.startswith(".") for part in path.relative_to(root).parts
                    ):
                        files.append(path)
                except OSError as exc:
                    raise MdsiteError(f"无法访问文件 {path}: {exc.strerror or exc}") from None
    except MdsiteError:
        raise
    except OSError as exc:
        raise MdsiteError(f"无法扫描目录 {root}: {exc.strerror or exc}") from None
    return files


_H1_TITLE_RE = re.compile(r"^#\s+(.+?)(?:\s+#+)?\s*$")


def _extract_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        match = _H1_TITLE_RE.match(line.strip())
        if match:
            title = _plain_text(match.group(1))
            if title:
                return title
    return fallback


def _render_toc(toc):
    """把 h2/h3 渲染为右侧目录；h3 嵌套在最近的 h2 内。"""
    if not toc:
        return ""

    lines = ['<nav class="toc-nav"><ul>']
    h2_open = False
    h3_open = False
    h3_without_h2 = False

    def close_h3() -> None:
        nonlocal h3_open
        if h3_open:
            lines.append("</ul>")
            h3_open = False

    def close_h2() -> None:
        nonlocal h2_open, h3_without_h2
        close_h3()
        if h2_open:
            lines.append("</li>")
            h2_open = False
            h3_without_h2 = False

    for level, text, anchor in toc:
        if level == 2:
            close_h2()
            lines.append(
                f'<li class="toc-h2"><a href="#{escape(anchor)}">{escape(text)}</a>'
            )
            h2_open = True
        elif level == 3:
            if not h2_open:
                # 容错：h3 在 h2 前直接出现时，使用普通外层 li 包裹嵌套列表。
                lines.append('<li class="toc-h2 orphan-h3"><ul>')
                h2_open = True
                h3_without_h2 = True
            if not h3_open:
                lines.append("<ul>")
                h3_open = True
            lines.append(
                f'<li class="toc-h3"><a href="#{escape(anchor)}">'
                f"{escape(text)}</a></li>"
            )
    close_h2()
    lines.append("</ul></nav>")
    return "\n".join(lines)


def _rewrite_markdown_links(html: str) -> str:
    """把生成内容中的相对 ``.md`` 链接改成对应 ``.html``。

    只处理解析器生成的 ``data-md-link``，因此块级 HTML 中的链接保持原样。
    """
    pattern = re.compile(r'<a data-md-link href="([^"]*)">')

    def replace(match):
        raw_attr = match.group(1)
        url = _html.unescape(raw_attr)
        if not url or url.startswith(("#", "//", "mailto:", "tel:")):
            new_url = url
        elif re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", url):
            new_url = url
        else:
            fragment = ""
            target = url
            if "#" in target:
                target, fragment = target.split("#", 1)
                fragment = "#" + fragment
            if target.lower().endswith(".md"):
                target = target[:-3] + ".html"
            new_url = target + fragment
        return f'<a href="{escape(new_url)}">'

    return pattern.sub(replace, html)


def _root_prefix(rel_path: Path) -> str:
    depth = len(rel_path.parts) - 1
    return "../" * depth


def _nav_links(pages: List[Tuple[Path, str]], root: str):
    links = [{"href": root + "index.html", "text": "首页"}]
    for rel, title in pages:
        href = rel.as_posix()
        if href == "index.html":
            continue
        links.append({"href": root + href, "text": title})
    return links


def build(input_dir, output_dir, theme="default", site_name=None):
    """构建静态站点，返回处理的 Markdown 文件数量。"""
    src = Path(input_dir)
    dst = Path(output_dir)

    if not src.exists():
        raise MdsiteError(f"输入目录不存在: {src}")
    if not src.is_dir():
        raise MdsiteError(f"输入路径不是目录: {src}")
    if theme not in available_themes():
        choices = ", ".join(available_themes())
        raise MdsiteError(f"未知主题 {theme!r}，可选: {choices}")

    src_resolved = src.resolve()
    dst_resolved = dst.resolve() if dst.exists() else dst.absolute()
    if dst_resolved == src_resolved:
        raise MdsiteError("输出目录不能和输入目录相同，请选择独立的输出路径")

    # 先收集文件，再创建输出目录；首次构建不会扫到生成物。重复构建时若输出目录
    # 位于输入目录内，则显式跳过它，避免把生成的 HTML 当输入再次处理。
    excluded = {dst_resolved} if _is_relative_to(dst_resolved, src_resolved) else set()
    source_files = _walk_files(src, excluded)
    markdown_files = [path for path in source_files if path.suffix == ".md"]
    asset_files = [path for path in source_files if path.suffix != ".md"]

    try:
        dst.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MdsiteError(f"无法创建输出目录 {dst}: {exc.strerror or exc}") from None

    site_name = site_name or src_resolved.name or "Docs"
    template_path = _PACKAGE_DIR / "templates" / "default.html"
    template = _read_text(template_path)

    rendered_pages = []
    pages: List[Tuple[Path, str]] = []

    for md_path in markdown_files:
        rel = md_path.relative_to(src).with_suffix(".html")
        markdown = _read_text(md_path)
        body, toc = render_markdown(markdown)
        body = _rewrite_markdown_links(body)
        title = _extract_title(markdown, md_path.stem)
        pages.append((rel, title))
        rendered_pages.append((rel, title, body, toc))

    pages.sort(key=lambda item: item[0].as_posix())

    for rel, title, body, toc in rendered_pages:
        root = _root_prefix(rel)
        try:
            html = render_template(template, {
                "title": escape(title),
                "site_name": escape(site_name),
                "content": body,
                "toc": _render_toc(toc),
                "has_toc": bool(toc),
                "theme": escape(theme),
                "root": root,
                "nav_links": _nav_links(pages, root),
            })
        except TemplateError as exc:
            raise MdsiteError(f"模板渲染失败 ({rel.as_posix()}): {exc}") from None
        _write_text(dst / rel, html)

    # 复制源目录图片等资源；输出目录位于源目录内时跳过生成物。
    for asset in asset_files:
        rel = asset.relative_to(src)
        target = dst / rel
        if _is_relative_to(asset.resolve(), dst.resolve()):
            continue
        _copy_file(asset, target)

    # 内置主题复制到 assets，后复制可以避免源目录中同名文件造成主题缺失。
    assets_dir = dst / "assets"
    try:
        assets_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MdsiteError(f"无法创建资源目录 {assets_dir}: {exc}") from None
    for theme_name in available_themes():
        _copy_file(
            _PACKAGE_DIR / "themes" / f"{theme_name}.css",
            assets_dir / f"{theme_name}.css",
        )
    _copy_file(
        _PACKAGE_DIR / "themes" / f"{theme}.css",
        assets_dir / "style.css",
    )

    if not (dst / "index.html").exists():
        _write_index(dst, pages, template, site_name, theme)

    return len(markdown_files)


def _write_index(dst: Path, pages: List[Tuple[Path, str]], template,
                 site_name: str, theme: str) -> None:
    items = []
    for rel, title in pages:
        href = rel.as_posix()
        if href == "index.html":
            continue
        items.append(f'<li><a href="{escape(href)}">{escape(title)}</a></li>')
    content = "<h1>{}</h1>\n<ul>{}</ul>".format(
        escape(site_name), "".join(items)
    )
    html = render_template(template, {
        "title": "首页",
        "site_name": escape(site_name),
        "content": content,
        "toc": "",
        "has_toc": False,
        "theme": escape(theme),
        "root": "",
        "nav_links": _nav_links(pages, ""),
    })
    _write_text(dst / "index.html", html)
