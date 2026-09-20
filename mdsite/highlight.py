"""基于正则规则的简易语法高亮器。不追求完美，覆盖常见情况即可。

支持：
- python：关键字、字符串、注释、数字、装饰器、内置函数
- 其他语言：通用规则（字符串、// 与 # 注释、数字）
- 无语言标注：仅转义
"""

import re
import html as _html

PY_KEYWORDS = (
    "False None True and as assert async await break class continue def del "
    "elif else except finally for from global if import in is lambda nonlocal "
    "not or pass raise return try while with yield match case"
).split()

PY_BUILTINS = (
    "print len range str int float list dict set tuple bool type isinstance "
    "enumerate zip map filter sorted open super self cls object Exception "
    "ValueError TypeError RuntimeError"
).split()

_PY_RE = re.compile(r"""
    (?P<comment>\#[^\n]*)
  | (?P<string>\"\"\".*?\"\"\"|\'\'\'.*?\'\'\'|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')
  | (?P<decorator>@[A-Za-z_][\w.]*)
  | (?P<number>\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b)
  | (?P<word>[A-Za-z_]\w*)
""", re.VERBOSE | re.DOTALL)

_GENERIC_RE = re.compile(r"""
    (?P<comment>//[^\n]*|/\*.*?\*/|\#[^\n]*)
  | (?P<string>"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')
  | (?P<number>\b\d+(?:\.\d+)?\b)
""", re.VERBOSE | re.DOTALL)

_BUILTIN_SET = set(PY_BUILTINS)
_KEYWORD_SET = set(PY_KEYWORDS)


def _span(cls, text):
    return '<span class="hl-%s">%s</span>' % (cls, _html.escape(text))


def _highlight_python(code):
    out, pos = [], 0
    for m in _PY_RE.finditer(code):
        if m.start() > pos:
            out.append(_html.escape(code[pos:m.start()]))
        kind = m.lastgroup
        text = m.group(0)
        if kind == "word":
            if text in _KEYWORD_SET:
                out.append(_span("kw", text))
            elif text in _BUILTIN_SET:
                out.append(_span("builtin", text))
            else:
                out.append(_html.escape(text))
        elif kind == "comment":
            out.append(_span("comment", text))
        elif kind == "string":
            out.append(_span("str", text))
        elif kind == "number":
            out.append(_span("num", text))
        elif kind == "decorator":
            out.append(_span("decorator", text))
        pos = m.end()
    out.append(_html.escape(code[pos:]))
    return "".join(out)


def _highlight_generic(code):
    out, pos = [], 0
    for m in _GENERIC_RE.finditer(code):
        if m.start() > pos:
            out.append(_html.escape(code[pos:m.start()]))
        kind = m.lastgroup
        cls = {"comment": "comment", "string": "str", "number": "num"}[kind]
        out.append(_span(cls, m.group(0)))
        pos = m.end()
    out.append(_html.escape(code[pos:]))
    return "".join(out)


def highlight_code(code, lang=""):
    """对代码做高亮并返回 HTML 安全字符串。未知语言仅转义。"""
    lang = (lang or "").lower()
    if lang in ("python", "py", "python3"):
        return _highlight_python(code)
    if lang in ("js", "javascript", "ts", "typescript", "java", "c", "cpp",
                "go", "rust", "sh", "bash", "shell", "css", "json", "yaml"):
        return _highlight_generic(code)
    return _html.escape(code)
