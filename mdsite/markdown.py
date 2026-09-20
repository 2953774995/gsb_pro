"""手写的小型 Markdown 解析器。

只使用 Python 标准库。对外主要暴露：

* ``render_markdown(text) -> (html, toc)``
* ``render_inline(text)``
* ``slugify(text)``
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass
from typing import List, Tuple

from .highlight import highlight_code


def escape(text: str) -> str:
    """转义文本，使它可以安全放入 HTML 文本或属性中。"""
    return _html.escape(str(text), quote=True)


_WHITESPACE_RE = re.compile(r"\s+")
_HTML_ENTITY_RE = re.compile(r"&(?:#[0-9]+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);")
_TAG_START_RE = re.compile(r"^<!---->|^<!--|^<!DOCTYPE\b|^</?[A-Za-z][A-Za-z0-9:-]*")


def _match_html_tag(text: str, start: int):
    """从 ``start`` 的 ``<`` 开始匹配一个 HTML 标签。

    属性值中的 ``>`` 需要当作属性内容处理。匹配失败返回 ``None``。
    """
    prefix = text[start:]
    if prefix.startswith("<!---->"):
        return start + 9
    if prefix.startswith("<!--"):
        end = text.find("-->", start + 4)
        return end + 3 if end != -1 else None
    if re.match(r"<!DOCTYPE\b", prefix, re.I):
        end = text.find(">", start)
        return end + 1 if end != -1 else None
    if not _TAG_START_RE.match(prefix):
        return None

    i = start + 1
    quote = ""
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == ">":
            return i + 1
        i += 1
    return None


def slugify(text: str) -> str:
    """把标题文本转换为稳定的 URL slug。

    规则：小写、空白转连字符、去除标点；``\\w`` 能保留中文等 Unicode 单词字符。
    """
    text = text.strip().lower()
    text = _WHITESPACE_RE.sub("-", text)
    text = re.sub(r"[^\w-]", "", text, flags=re.UNICODE)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "section"


class Slugger:
    """为一篇文档内重复标题生成唯一锚点。"""

    def __init__(self) -> None:
        self.seen = {}

    def slug(self, text: str) -> str:
        base = slugify(text)
        count = self.seen.get(base, 0)
        self.seen[base] = count + 1
        return base if count == 0 else f"{base}-{count}"


@dataclass
class _Token:
    kind: str
    value: str = ""
    raw: str = ""


def _find_closing(text: str, start: int, open_ch: str, close_ch: str) -> int:
    """寻找配对闭合符号，支持嵌套和反斜杠转义。"""
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            i += 2
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _tokenize_inline(text: str) -> List[_Token]:
    tokens: List[_Token] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]

        if ch == "`":
            j = text.find("`", i + 1)
            if j != -1:
                tokens.append(_Token("code", text[i + 1:j]))
                i = j + 1
                continue

        if ch == "!" and i + 1 < n and text[i + 1] == "[":
            close = _find_closing(text, i + 1, "[", "]")
            if close != -1 and close + 1 < n and text[close + 1] == "(":
                end = _find_closing(text, close + 1, "(", ")")
                if end != -1:
                    tokens.append(_Token(
                        "image",
                        text[close + 2:end].strip(),
                        text[i + 2:close],
                    ))
                    i = end + 1
                    continue

        if ch == "[":
            close = _find_closing(text, i, "[", "]")
            if close != -1 and close + 1 < n and text[close + 1] == "(":
                end = _find_closing(text, close + 1, "(", ")")
                if end != -1:
                    tokens.append(_Token(
                        "link",
                        text[close + 2:end].strip(),
                        text[i + 1:close],
                    ))
                    i = end + 1
                    continue

        if text.startswith("**", i):
            j = text.find("**", i + 2)
            if j != -1 and j > i + 2 and not text[i + 2].isspace():
                tokens.append(_Token("strong", text[i + 2:j]))
                i = j + 2
                continue

        if ch == "*" and not text.startswith("**", i):
            j = text.find("*", i + 1)
            if j != -1 and j > i + 1 and not text[i + 1].isspace():
                tokens.append(_Token("em", text[i + 1:j]))
                i = j + 1
                continue

        if ch == "<":
            end = _match_html_tag(text, i)
            if end is not None:
                tokens.append(_Token("html", text[i:end]))
                i = end
                continue
            tokens.append(_Token("text", "&lt;"))
            i += 1
            continue

        if ch == ">":
            tokens.append(_Token("text", "&gt;"))
            i += 1
            continue

        if ch == "&" and _HTML_ENTITY_RE.match(text, i):
            m = _HTML_ENTITY_RE.match(text, i)
            tokens.append(_Token("text", m.group(0)))
            i = m.end()
            continue

        if ch == "&" and _HTML_ENTITY_RE.match(text, i):
            match = _HTML_ENTITY_RE.match(text, i)
            tokens.append(_Token("text", match.group(0)))
            i = match.end()
            continue
        if ch == "&":
            tokens.append(_Token("text", "&amp;"))
            i += 1
            continue

        if ch == "\\" and i + 1 < n:
            tokens.append(_Token("text", escape(text[i + 1])))
            i += 2
            continue

        tokens.append(_Token("text", ch))
        i += 1
    return tokens


def render_inline(text: str) -> str:
    """渲染行内 Markdown。代码 span 内部不会再解析其它行内语法。"""
    out = []
    for tok in _tokenize_inline(text):
        if tok.kind == "text":
            out.append(tok.value)
        elif tok.kind == "html":
            out.append(tok.value)
        elif tok.kind == "code":
            out.append(f"<code>{escape(tok.value)}</code>")
        elif tok.kind == "strong":
            out.append(f"<strong>{render_inline(tok.value)}</strong>")
        elif tok.kind == "em":
            out.append(f"<em>{render_inline(tok.value)}</em>")
        elif tok.kind == "link":
            out.append(
                f'<a data-md-link href="{escape(tok.value)}">'
                f"{render_inline(tok.raw)}</a>"
            )
        elif tok.kind == "image":
            out.append(
                f'<img src="{escape(tok.value)}" alt="{escape(tok.raw)}">'
            )
    return "".join(out)

def _plain_text(text: str) -> str:
    """从行内 Markdown 提取纯文本，用于 title、TOC、锚点。"""
    out = []
    for tok in _tokenize_inline(text):
        if tok.kind in ("text", "code", "strong", "em"):
            value = tok.value
            if tok.kind == "text":
                # 这里的 text 已经做了实体转换，还原后再交给 slug/escape。
                value = _html.unescape(value)
            out.append(value)
        elif tok.kind in ("link", "image"):
            out.append(_plain_text(tok.raw))
        # html token 不参与标题文本
    return "".join(out).strip()


_HEADING_RE = re.compile(r"^(\s{0,3})(#{1,6})(?:[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*)?$")
_FENCE_RE = re.compile(r"^(\s{0,3})(`{3,}|~{3,})[ \t]*(.*?)\s*$")
_FENCE_END_RE = {
    "`": re.compile(r"^\s{0,3}(`{3,})\s*$"),
    "~": re.compile(r"^\s{0,3}(~{3,})\s*$"),
}
_HR_RE = re.compile(r"^\s{0,3}(?:-\s*-{2,}|\*\s*\*{2,}|_\s*_{2,})\s*$")
_LIST_RE = re.compile(r"^(\s*)(?:([-*+])|(\d{1,9})([.)]))[ \t]+(.*\S)?\s*$")
_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "canvas", "dd", "details",
    "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "iframe", "li",
    "main", "nav", "noscript", "ol", "p", "pre", "script", "section",
    "style", "table", "tbody", "td", "template", "tfoot", "th", "thead",
    "tr", "ul", "video",
}
_BLOCK_OPEN_RE = re.compile(r"^\s*<\s*([A-Za-z][A-Za-z0-9-]*)[\s>/]")


def _is_table_delimiter(line: str) -> bool:
    cells = _split_table_row_raw(line)
    cells = [c for c in cells if c != ""]
    if not cells:
        return False
    return all(re.fullmatch(r":?-{1,}:?", c.replace(" ", "")) for c in cells)


def _split_table_row_raw(line: str) -> List[str]:
    """按未转义的 ``|`` 分列，并保留转义反斜杠给分隔行校验。"""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [part.strip() for part in re.split(r"(?<!\\)\|", line)]


def split_table_row(line: str) -> List[str]:
    """拆分表格行，未转义的 ``|`` 分列，``\\|`` 表示字面量竖线。"""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("\\|"):
        # 尾部转义竖线不能被当作可选的表格边界。
        pass
    elif line.endswith("|"):
        line = line[:-1]

    cells: List[List[str]] = [[]]
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            if line[i + 1] == "|":
                cells[-1].append("|")
            else:
                cells[-1].append(line[i:i + 2])
            i += 2
        elif ch == "|":
            cells.append([])
            i += 1
        else:
            cells[-1].append(ch)
            i += 1
    return ["".join(parts).strip() for parts in cells]


def _is_list_item(line: str) -> bool:
    return bool(_LIST_RE.match(line))


def _is_html_block_start(line: str) -> bool:
    if line.lstrip().startswith("<!--") or line.lstrip().lower().startswith("<!doctype"):
        return True
    match = _BLOCK_OPEN_RE.match(line)
    return bool(match and match.group(1).lower() in _BLOCK_TAGS)


TocItem = Tuple[int, str, str]

@dataclass
class _ListItem:
    indent: int
    ordered: bool
    text: str
    level: int = 0


class MarkdownParser:
    def __init__(self, text: str) -> None:
        self.lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self.slugger = Slugger()
        self.toc: List[TocItem] = []

    def parse(self) -> str:
        html_parts = []
        i = 0
        while i < len(self.lines):
            line = self.lines[i]
            if not line.strip():
                i += 1
                continue

            fence = _FENCE_RE.match(line)
            if fence:
                block, i = self.code_block(i, fence)
                html_parts.append(block)
                continue

            heading = _HEADING_RE.match(line)
            if heading:
                html_parts.append(self.heading(heading))
                i += 1
                continue

            if line.lstrip().startswith(">"):
                block, i = self.blockquote(i)
                html_parts.append(block)
                continue

            if _HR_RE.match(line):
                html_parts.append("<hr>")
                i += 1
                continue

            if _is_list_item(line):
                block, i = self.list_block(i)
                html_parts.append(block)
                continue

            if "|" in line and i + 1 < len(self.lines) and _is_table_delimiter(self.lines[i + 1]):
                block, i = self.table(i)
                html_parts.append(block)
                continue

            if _is_html_block_start(line):
                block, i = self.html_block(i)
                html_parts.append(block)
                continue

            block, i = self.paragraph(i)
            html_parts.append(block)
        return "\n".join(html_parts)

    def heading(self, match: re.Match) -> str:
        level = len(match.group(2))
        raw = (match.group(3) or "").strip()
        title = _plain_text(raw)
        anchor = self.slugger.slug(title)
        if level in (2, 3):
            self.toc.append((level, title, anchor))
        return f'<h{level} id="{escape(anchor)}">{render_inline(raw)}</h{level}>'

    def code_block(self, i: int, fence_match: re.Match) -> Tuple[str, int]:
        marker = fence_match.group(2)
        kind = marker[0]
        min_len = len(marker)
        info = (fence_match.group(3) or "").strip()
        lang = info.split()[0] if info else ""
        body = []
        i += 1
        while i < len(self.lines):
            closing = _FENCE_END_RE[kind].match(self.lines[i])
            if closing and len(closing.group(1)) >= min_len:
                i += 1
                break
            body.append(self.lines[i])
            i += 1
        code = "\n".join(body)
        lang_attr = f' class="language-{escape(lang)}"' if lang else ""
        return f"<pre><code{lang_attr}>{highlight_code(code, lang)}</code></pre>", i

    def blockquote(self, i: int) -> Tuple[str, int]:
        buf = []
        while i < len(self.lines):
            line = self.lines[i]
            stripped = line.lstrip()
            if stripped.startswith(">"):
                content = stripped[1:]
                if content.startswith(" "):
                    content = content[1:]
                buf.append(content)
                i += 1
            elif not line.strip() and i + 1 < len(self.lines) and self.lines[i + 1].lstrip().startswith(">"):
                buf.append("")
                i += 1
            else:
                break
        nested = MarkdownParser("\n".join(buf))
        nested.slugger = self.slugger
        rendered = nested.parse()
        self.toc.extend(nested.toc)
        return f"<blockquote>\n{rendered}\n</blockquote>", i

    def _collect_list_items(self, i: int) -> Tuple[List[_ListItem], int]:
        items: List[_ListItem] = []
        while i < len(self.lines):
            line = self.lines[i]
            if not line.strip():
                # 允许列表项之间有空行；空行后若不是列表则结束。
                j = i + 1
                while j < len(self.lines) and not self.lines[j].strip():
                    j += 1
                if j < len(self.lines) and _is_list_item(self.lines[j]):
                    i = j
                    continue
                break
            match = _LIST_RE.match(line)
            if not match:
                break
            indent = len(match.group(1).expandtabs(4))
            ordered = match.group(3) is not None
            items.append(_ListItem(indent, ordered, match.group(5) or ""))
            i += 1
        return items, i

    def list_block(self, i: int) -> Tuple[str, int]:
        items, next_i = self._collect_list_items(i)
        if not items:
            return self.paragraph(i)

        # 缩进宽度在真实文档里可能混用 2/4 空格。这里按“比父项深即下一层”
        # 的方式归一化为整数层级，避免生成同级互相嵌套的非法 HTML。
        stack = [(0, items[0].indent)]
        for item in items:
            while item.indent < stack[-1][1]:
                stack.pop()
            if item.indent == stack[-1][1]:
                item.level = stack[-1][0]
            else:
                level = stack[-1][0] + 1
                item.level = level
                stack.append((level, item.indent))
        return self.render_list(items, 0, 0)[0], next_i

    def render_list(self, items: List[_ListItem], index: int,
                    level: int) -> Tuple[str, int]:
        ordered = items[index].ordered
        tag = "ol" if ordered else "ul"
        parts = [f"<{tag}>"]
        while index < len(items):
            item = items[index]
            if item.level < level:
                break
            if item.level > level:
                nested, index = self.render_list(items, index, item.level)
                parts[-1] += nested
                continue
            parts.append(f"<li>{render_inline(item.text)}")
            index += 1
            if index < len(items) and items[index].level > level:
                nested, index = self.render_list(items, index, items[index].level)
                parts[-1] += nested
            parts[-1] += "</li>"
        parts.append(f"</{tag}>")
        return "".join(parts), index
    def table(self, i: int) -> Tuple[str, int]:
        headers = split_table_row(self.lines[i])
        delimiter = split_table_row(self.lines[i + 1])
        alignments = []
        for cell in delimiter:
            compact = cell.replace(" ", "")
            alignments.append(
                "center" if compact.startswith(":") and compact.endswith(":")
                else "left" if compact.startswith(":")
                else "right" if compact.endswith(":")
                else None
            )
        i += 2
        rows = []
        while i < len(self.lines) and self.lines[i].strip() and "|" in self.lines[i]:
            rows.append(split_table_row(self.lines[i]))
            i += 1

        def alignment_attr(column: int) -> str:
            value = alignments[column] if column < len(alignments) else None
            return f' align="{value}"' if value else ""

        out = ["<table>", "<thead><tr>"]
        for column, header in enumerate(headers):
            out.append(f"<th{alignment_attr(column)}>{render_inline(header)}</th>")
        out.append("</tr></thead>")
        if rows:
            out.append("<tbody>")
            for row in rows:
                out.append("<tr>")
                for column in range(len(headers)):
                    cell = row[column] if column < len(row) else ""
                    out.append(f"<td{alignment_attr(column)}>{render_inline(cell)}</td>")
                out.append("</tr>")
            out.append("</tbody>")
        out.append("</table>")
        return "\n".join(out), i

    def html_block(self, i: int) -> Tuple[str, int]:
        first = self.lines[i]
        lower = first.lstrip().lower()
        if lower.startswith("<!--"):
            buf = []
            while i < len(self.lines):
                buf.append(self.lines[i])
                if "-->" in self.lines[i]:
                    i += 1
                    break
                i += 1
            return "\n".join(buf), i
        if lower.startswith("<!doctype") or (
            _BLOCK_OPEN_RE.match(first)
            and (first.rstrip().endswith("/>") or self._single_line_block(first))
        ):
            return first, i + 1

        match = _BLOCK_OPEN_RE.match(first)
        tag = match.group(1).lower() if match else ""
        close_re = re.compile(rf"</\s*{re.escape(tag)}\s*>", re.I)
        buf = []
        while i < len(self.lines):
            current = self.lines[i]
            buf.append(current)
            i += 1
            if tag and close_re.search(current):
                break
            if not current.strip() and tag:
                break
        return "\n".join(buf), i

    @staticmethod
    def _single_line_block(line: str) -> bool:
        match = _BLOCK_OPEN_RE.match(line)
        if not match:
            return False
        tag = match.group(1).lower()
        return bool(re.search(rf"</\s*{re.escape(tag)}\s*>\s*$", line, re.I))

    def paragraph(self, i: int) -> Tuple[str, int]:
        buf = []
        while i < len(self.lines):
            line = self.lines[i]
            if not line.strip():
                break
            if buf:
                stripped = line.lstrip()
                if (
                    _FENCE_RE.match(line)
                    or _HEADING_RE.match(line)
                    or _HR_RE.match(line)
                    or _is_list_item(line)
                    or stripped.startswith(">")
                    or _is_html_block_start(line)
                    or ("|" in line
                        and i + 1 < len(self.lines)
                        and _is_table_delimiter(self.lines[i + 1]))
                ):
                    break
            buf.append(line.strip())
            i += 1
        return f"<p>{render_inline(' '.join(buf))}</p>", i


def render_markdown(text: str) -> Tuple[str, List[TocItem]]:
    """渲染 Markdown，返回 ``(HTML 片段, h2/h3 目录数据)``。"""
    parser = MarkdownParser(text)
    rendered = parser.parse()
    return rendered, parser.toc
