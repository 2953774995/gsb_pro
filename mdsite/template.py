"""自实现的极简模板引擎（仅标准库）。

支持：
    {{ name }}            变量替换（支持点号取值，如 {{ item.title }}）
    {% if name %}         条件块，{% endif %} 结束
    {% for x in items %}  循环块，{% endfor %} 结束

变量值原样插入（不做 HTML 转义），需要转义的内容由调用方先处理好。
"""
from __future__ import annotations

import re

from .errors import MdsiteError

_TOKEN_RE = re.compile(r"({{.*?}}|{%.*?%})", re.S)


def _resolve(expr: str, context):
    parts = expr.strip().split(".")
    if not parts[0]:
        raise MdsiteError("模板表达式为空")
    if parts[0] not in context:
        raise MdsiteError("模板变量未定义: %s" % parts[0])
    value = context[parts[0]]
    for part in parts[1:]:
        if isinstance(value, dict):
            if part not in value:
                raise MdsiteError("模板变量未定义: %s" % expr)
            value = value[part]
        else:
            value = getattr(value, part)
    return value


def _parse(tokens, i, end_tags):
    """返回 (nodes, next_index, matched_end_tag_or_None)。"""
    nodes = []
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("{{") and tok.endswith("}}"):
            nodes.append(("var", tok[2:-2].strip()))
            i += 1
        elif tok.startswith("{%") and tok.endswith("%}"):
            tag = tok[2:-2].strip()
            name = tag.split(None, 1)[0] if tag else ""
            if name in end_tags:
                return nodes, i + 1, name
            if name == "if":
                expr = tag[2:].strip()
                if not expr:
                    raise MdsiteError("{% if %} 缺少条件表达式")
                body, i, end = _parse(tokens, i + 1, ("endif",))
                if end is None:
                    raise MdsiteError("{%% if %s %%} 缺少 {%% endif %%}" % expr)
                nodes.append(("if", expr, body))
            elif name == "for":
                m = re.match(r"for\s+(\w+)\s+in\s+(.+)$", tag)
                if not m:
                    raise MdsiteError("for 标签语法错误: %s" % tag)
                var, expr = m.group(1), m.group(2).strip()
                body, i, end = _parse(tokens, i + 1, ("endfor",))
                if end is None:
                    raise MdsiteError("{%% for %s %%} 缺少 {%% endfor %%}" % tag)
                nodes.append(("for", var, expr, body))
            elif name in ("endif", "endfor"):
                raise MdsiteError("多余的 {%% %s %%}" % name)
            else:
                raise MdsiteError("未知模板标签: %s" % tag)
        else:
            nodes.append(("text", tok))
            i += 1
    return nodes, i, None


def _render_nodes(nodes, context, out):
    for node in nodes:
        kind = node[0]
        if kind == "text":
            out.append(node[1])
        elif kind == "var":
            out.append(str(_resolve(node[1], context)))
        elif kind == "if":
            if _resolve(node[1], context):
                _render_nodes(node[2], context, out)
        elif kind == "for":
            _, var, expr, body = node
            items = _resolve(expr, context)
            for item in items:
                child = dict(context)
                child[var] = item
                _render_nodes(body, child, out)


def render(template: str, context: dict) -> str:
    tokens = _TOKEN_RE.split(template)
    nodes, _, _ = _parse(tokens, 0, ())
    out = []
    _render_nodes(nodes, context, out)
    return "".join(out)
