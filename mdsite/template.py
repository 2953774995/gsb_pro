"""一个很小的模板引擎。

支持：

``{{ variable }}``
    变量输出，支持属性/字典路径，例如 ``{{ page.title }}``。
``{% if expression %} ... {% else %} ... {% endif %}``
    支持简单真值判断和 ``not``。
``{% for item in items %} ... {% endfor %}``
    遍历列表/元组等可迭代对象。

模板默认不做 HTML 转义；由调用方在传入用户内容前决定哪些字段需要转义。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

_TOKEN_RE = re.compile(r"({{.*?}}|{%.*?%})", re.S)
_FOR_RE = re.compile(r"^for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+(.+)$")


class TemplateError(Exception):
    """模板语法或变量错误。"""


def _lookup(expr: str, ctx: Dict[str, Any]) -> Any:
    expr = expr.strip()
    if not expr:
        raise TemplateError("empty expression")

    # 仅支持模板内部常用的字符串/数字常量。
    if len(expr) >= 2 and expr[0] in "\"'" and expr[-1] == expr[0]:
        return expr[1:-1]
    if re.fullmatch(r"\d+", expr):
        return int(expr)

    value: Any = ctx
    for part in expr.split("."):
        part = part.strip()
        if not part:
            raise TemplateError(f"bad expression: {expr}")
        if isinstance(value, dict):
            if part not in value:
                raise TemplateError(f"undefined variable: {expr}")
            value = value[part]
        else:
            if not hasattr(value, part):
                raise TemplateError(f"undefined variable: {expr}")
            value = getattr(value, part)
    return value


def _eval(expr: str, ctx: Dict[str, Any]) -> Any:
    expr = expr.strip()
    if expr.startswith("not "):
        return not _lookup(expr[4:].strip(), ctx)
    return _lookup(expr, ctx)


class _Node:
    def render(self, ctx: Dict[str, Any]) -> str:
        raise NotImplementedError


class _Text(_Node):
    def __init__(self, text: str):
        self.text = text

    def render(self, ctx: Dict[str, Any]) -> str:
        return self.text


class _Variable(_Node):
    def __init__(self, expression: str):
        self.expression = expression

    def render(self, ctx: Dict[str, Any]) -> str:
        value = _eval(self.expression, ctx)
        return "" if value is None else str(value)


class _If(_Node):
    def __init__(self, expression, body, else_body):
        self.expression = expression
        self.body = body
        self.else_body = else_body

    def render(self, ctx: Dict[str, Any]) -> str:
        nodes = self.body if _eval(self.expression, ctx) else self.else_body
        return "".join(node.render(ctx) for node in nodes)


class _For(_Node):
    def __init__(self, variable, expression, body):
        self.variable = variable
        self.expression = expression
        self.body = body

    def render(self, ctx: Dict[str, Any]) -> str:
        result = []
        try:
            iterable = _lookup(self.expression, ctx)
            for item in iterable:
                child = dict(ctx)
                child[self.variable] = item
                result.append("".join(node.render(child) for node in self.body))
        except TypeError as exc:
            raise TemplateError(f"not iterable: {self.expression}") from exc
        return "".join(result)


def _parse(tokens: List[str], pos: int, end_tags=()):
    nodes: List[_Node] = []
    while pos < len(tokens):
        token = tokens[pos]
        if token.startswith("{{"):
            nodes.append(_Variable(token[2:-2].strip()))
            pos += 1
        elif token.startswith("{%"):
            tag = token[2:-2].strip()
            keyword = tag.split(None, 1)[0] if tag else ""
            if keyword in end_tags:
                return nodes, pos, tag
            if keyword == "if":
                expression = tag[2:].strip()
                if not expression:
                    raise TemplateError("if requires an expression")
                body, pos, stop = _parse(tokens, pos + 1, ("else", "endif"))
                else_body: List[_Node] = []
                if stop == "else":
                    else_body, pos, stop = _parse(tokens, pos + 1, ("endif",))
                if stop != "endif":
                    raise TemplateError("missing endif")
                nodes.append(_If(expression, body, else_body))
                pos += 1
            elif keyword == "for":
                match = _FOR_RE.match(tag)
                if not match:
                    raise TemplateError(f"bad for tag: {tag}")
                body, pos, stop = _parse(tokens, pos + 1, ("endfor",))
                if stop != "endfor":
                    raise TemplateError("missing endfor")
                nodes.append(_For(match.group(1), match.group(2).strip(), body))
                pos += 1
            elif keyword in ("else", "endif", "endfor"):
                raise TemplateError(f"unexpected tag: {tag}")
            else:
                raise TemplateError(f"unknown tag: {tag}")
        else:
            nodes.append(_Text(token))
            pos += 1
    if end_tags:
        raise TemplateError("missing " + " / ".join(end_tags))
    return nodes, pos, None


def render_template(template: str, context: Dict[str, Any]) -> str:
    """渲染模板字符串。"""
    tokens = _TOKEN_RE.split(template)
    nodes, _, _ = _parse(tokens, 0)
    return "".join(node.render(context) for node in nodes)
