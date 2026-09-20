"""自实现的 Markdown 解析器（仅标准库）。

用法：
    html, toc, title = render_page(markdown_text)

- html: 渲染后的 HTML 片段
- toc:  [(level, anchor, text), ...]  从 h2/h3 提取
- title: 第一个 h1 的纯文本（没有则为 None）
"""
from __future__ import annotations

import html as _html
import re

from .highlight import highlight_code

# ---------------------------------------------------------------------------
# 块级语法
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
_HR_RE = re.compile(r"^[ \t]*((-[ \t]*){3,}|(\*[ \t]*){3,}|(_[ \t]*){3,})$")
_FENCE_RE = re.compile(r"^[ \t]*```([^`]*)$")
_ULIST_RE = re.compile(r"^( *)[-*+][ \t]+(.*)$")
_OLIST_RE = re.compile(r"^( *)\d+[.)][ \t]+(.*)$")
_QUOTE_RE = re.compile(r"^[ \t]*>[ \t]?(.*)$")
_BLOCK_HTML_RE = re.compile(r"^[ \t]*(<!--|</?[A-Za-z][A-Za-z0-9-]*(\s|>|/>))")
_TABLE_SEP_RE = re.compile(
    r"^[ \t]*\|?[ \t]*:?-+:?[ \t]*(\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$"
)


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_table_start(lines, i) -> bool:
    return (
        i + 1 < len(lines)
        and "|" in lines[i]
        and bool(_TABLE_SEP_RE.match(lines[i + 1]))
    )


def _starts_block(lines, i) -> bool:
    line = lines[i]
    return bool(
        _FENCE_RE.match(line)
        or _HEADING_RE.match(line)
        or _HR_RE.match(line)
        or _QUOTE_RE.match(line)
        or _ULIST_RE.match(line)
        or _OLIST_RE.match(line)
        or _BLOCK_HTML_RE.match(line)
        or _is_table_start(lines, i)
    )


def _split_table_row(line: str):
    """切分表格行，支持 \\| 转义。"""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    cells, buf = [], []
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line) and line[i + 1] == "|":
            buf.append("|")
            i += 2
        elif c == "|":
            cells.append("".join(buf))
            buf = []
            i += 1
        else:
            buf.append(c)
            i += 1
    cells.append("".join(buf))
    return [c.strip() for c in cells]


def _parse_table(lines, i):
    headers = _split_table_row(lines[i])
    i += 2  # 跳过表头行和分隔行
    rows = []
    while i < len(lines) and lines[i].strip() and "|" in lines[i]:
        row = _split_table_row(lines[i])
        # 列数对齐：少了补空，多了截断
        if len(row) < len(headers):
            row += [""] * (len(headers) - len(row))
        rows.append(row[: len(headers)])
        i += 1
    return ("table", headers, rows), i


def _parse_list(lines, i):
    """解析列表，支持嵌套。对 2/4 空格混用的缩进宽容处理。"""
    ordered = bool(_OLIST_RE.match(lines[i]))
    marker_re = _OLIST_RE if ordered else _ULIST_RE
    base_indent = _indent_of(lines[i])
    items = []  # (content, sub_lines)
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            break
        m = marker_re.match(line)
        if not m or len(m.group(1)) != base_indent:
            break
        content = m.group(2)
        i += 1
        sub = []
        while i < n and lines[i].strip() and _indent_of(lines[i]) > base_indent:
            sub.append(lines[i])
            i += 1
        items.append((content, sub))
    rendered = []
    for content, sub in items:
        sub_blocks = []
        if sub:
            dedent = min(_indent_of(s) for s in sub)
            sub_blocks = parse_blocks([s[dedent:] for s in sub])
        rendered.append((content, sub_blocks))
    return ("list", ordered, rendered), i


def parse_blocks(lines):
    """把行序列解析成块级 AST。"""
    blocks = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        m = _FENCE_RE.match(line)
        if m:
            lang = m.group(1).strip()
            buf = []
            j = i + 1
            while j < n and not _FENCE_RE.match(lines[j]):
                buf.append(lines[j])
                j += 1
            blocks.append(("code", lang, "\n".join(buf)))
            i = j + 1 if j < n else j
            continue

        m = _HEADING_RE.match(line)
        if m:
            blocks.append(("heading", len(m.group(1)), m.group(2).strip()))
            i += 1
            continue

        if _HR_RE.match(line):
            blocks.append(("hr",))
            i += 1
            continue

        m = _QUOTE_RE.match(line)
        if m:
            buf = []
            while i < n and _QUOTE_RE.match(lines[i]):
                buf.append(_QUOTE_RE.match(lines[i]).group(1))
                i += 1
            blocks.append(("quote", parse_blocks(buf)))
            continue

        if _ULIST_RE.match(line) or _OLIST_RE.match(line):
            block, i = _parse_list(lines, i)
            blocks.append(block)
            continue

        if _is_table_start(lines, i):
            block, i = _parse_table(lines, i)
            blocks.append(block)
            continue

        if _BLOCK_HTML_RE.match(line):
            buf = []
            while i < n and lines[i].strip():
                buf.append(lines[i])
                i += 1
            blocks.append(("html", "\n".join(buf)))
            continue

        # 段落：直到空行或下一个块级元素
        buf = [line]
        i += 1
        while i < n and lines[i].strip() and not _starts_block(lines, i):
            buf.append(lines[i])
            i += 1
        blocks.append(("para", "\n".join(buf)))
    return blocks


# ---------------------------------------------------------------------------
# 行内语法
# ---------------------------------------------------------------------------

# URL 允许一层嵌套括号，如 [x](http://a/b_(1))
_URL = r"(?:\\.|[^()\\\s]|\([^()]*\))*"
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\((" + _URL + r")\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\((" + _URL + r")\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
_ITALIC_RE = re.compile(r"\*([^*\n]+)\*")
_CODE_RE = re.compile(r"`([^`]+)`")
_HTML_TAG_RE = re.compile(r"<!--.*?-->|</?[A-Za-z][^>]*?>", re.S)


def _esc(text: str) -> str:
    return _html.escape(text, quote=False)


def _esc_attr(text: str) -> str:
    return _html.escape(text, quote=True)


def plain_text(text: str) -> str:
    """去掉行内标记，只留纯文本（用于 TOC 显示和 slug）。"""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("**", "").replace("*", "").replace("`", "")
    text = re.sub(r"</?[A-Za-z][^>]*>", "", text)
    return text.strip()


def render_inline(text: str) -> str:
    """渲染行内元素。普通文本一律 HTML 转义，行内 HTML 原样透传。"""
    out = []
    i, n = 0, len(text)
    while i < n:
        m = _IMAGE_RE.match(text, i)
        if m:
            alt, src = m.group(1), m.group(2)
            out.append(
                '<img src="%s" alt="%s">' % (_esc_attr(src), _esc_attr(plain_text(alt)))
            )
            i = m.end()
            continue
        m = _LINK_RE.match(text, i)
        if m:
            label, url = m.group(1), m.group(2)
            out.append('<a href="%s">%s</a>' % (_esc_attr(url), render_inline(label)))
            i = m.end()
            continue
        m = _BOLD_RE.match(text, i)
        if m:
            out.append("<strong>%s</strong>" % render_inline(m.group(1)))
            i = m.end()
            continue
        m = _ITALIC_RE.match(text, i)
        if m:
            out.append("<em>%s</em>" % render_inline(m.group(1)))
            i = m.end()
            continue
        m = _CODE_RE.match(text, i)
        if m:
            out.append("<code>%s</code>" % _esc(m.group(1)))
            i = m.end()
            continue
        m = _HTML_TAG_RE.match(text, i)
        if m:
            out.append(m.group(0))  # 行内 HTML 原样透传
            i = m.end()
            continue
        out.append(_esc(text[i]))
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------


def slugify(text: str) -> str:
    """标题文本 -> 锚点 id：小写、空白转连字符、去标点。中文按词符保留。"""
    s = plain_text(text).lower()
    s = re.sub(r"[^\w\s-]", "", s)  # \w 在 Unicode 模式下包含中文
    s = re.sub(r"\s+", "-", s)
    return s.strip("-") or "section"


class Slugger:
    """同一页面内生成不重复的锚点 id。"""

    def __init__(self):
        self._seen = {}

    def slug(self, text: str) -> str:
        base = slugify(text)
        count = self._seen.get(base, 0)
        self._seen[base] = count + 1
        return base if count == 0 else "%s-%d" % (base, count)


def render_blocks(blocks, toc=None, slugger=None) -> str:
    if slugger is None:
        slugger = Slugger()
    out = []
    for b in blocks:
        kind = b[0]
        if kind == "code":
            out.append(highlight_code(b[2], b[1]))
        elif kind == "heading":
            level, text = b[1], b[2]
            hid = slugger.slug(text)
            if toc is not None and level in (2, 3):
                toc.append((level, hid, plain_text(text)))
            out.append('<h%d id="%s">%s</h%d>' % (level, hid, render_inline(text), level))
        elif kind == "quote":
            out.append("<blockquote>%s</blockquote>" % render_blocks(b[1], toc, slugger))
        elif kind == "list":
            tag = "ol" if b[1] else "ul"
            lis = []
            for content, sub in b[2]:
                inner = render_inline(content)
                if sub:
                    inner += render_blocks(sub, toc, slugger)
                lis.append("<li>%s</li>" % inner)
            out.append("<%s>%s</%s>" % (tag, "".join(lis), tag))
        elif kind == "table":
            headers, rows = b[1], b[2]
            thead = "".join("<th>%s</th>" % render_inline(c) for c in headers)
            body = "".join(
                "<tr>%s</tr>" % "".join("<td>%s</td>" % render_inline(c) for c in row)
                for row in rows
            )
            out.append(
                "<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>"
                % (thead, body)
            )
        elif kind == "hr":
            out.append("<hr>")
        elif kind == "html":
            out.append(b[1])  # 块级 HTML 原样输出
        elif kind == "para":
            out.append("<p>%s</p>" % render_inline(b[1]))
    return "\n".join(out)


def render_page(text: str):
    """解析一整篇 Markdown，返回 (html, toc, title)。"""
    blocks = parse_blocks(text.split("\n"))
    toc = []
    body = render_blocks(blocks, toc, Slugger())
    title = None
    for b in blocks:
        if b[0] == "heading" and b[1] == 1:
            title = plain_text(b[2])
            break
    return body, toc, title


def render_html(text: str) -> str:
    """只要 HTML 片段时的便捷入口。"""
    return render_page(text)[0]
