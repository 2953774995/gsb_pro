"""基于规则的简单语法高亮器（仅标准库）。

不追求完美解析，只对注释 / 字符串 / 数字 / 关键词做正则着色。
目前内置 python 规则，其它语言原样转义输出。
"""
from __future__ import annotations

import html
import re

_PY_KEYWORDS = (
    "def class return if elif else for while import from as with try except "
    "finally raise lambda yield pass break continue and or not in is del global "
    "nonlocal assert async await None True False print self"
).split()

_TOKEN_RE = re.compile(
    r"""
    (?P<comment>\#[^\n]*)
    |(?P<string>'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*")
    |(?P<number>\b\d+(?:\.\d+)?\b)
    |(?P<keyword>\b(?:""" + "|".join(_PY_KEYWORDS) + r""")\b)
    """,
    re.X,
)

_SPAN_CLASS = {
    "comment": "tok-c",
    "string": "tok-s",
    "number": "tok-n",
    "keyword": "tok-k",
}

_PY_ALIASES = {"python", "py", "python3"}


def _colorize(m: re.Match) -> str:
    kind = m.lastgroup
    return '<span class="%s">%s</span>' % (_SPAN_CLASS[kind], m.group(0))


def highlight_code(code: str, lang: str = "") -> str:
    """把代码块渲染成 <pre><code>，按需做着色。内容一律先 HTML 转义。"""
    lang = (lang or "").strip().lower()
    # quote=False：保留引号，方便字符串规则匹配；< > & 仍会被转义
    escaped = html.escape(code, quote=False)
    if lang in _PY_ALIASES:
        escaped = _TOKEN_RE.sub(_colorize, escaped)
    cls = ' class="language-%s"' % html.escape(lang, quote=True) if lang else ""
    return "<pre><code%s>%s</code></pre>" % (cls, escaped)
