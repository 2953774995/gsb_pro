"""Parse token streams into AST node trees."""

import re

from .errors import TplError
from .expression import parse_expression, parse_output
from . import nodes as ast_nodes

_FOR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s+in\s+(.+)$", re.DOTALL)
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_END_TAGS = ("endif", "endfor", "endblock", "elif", "else")


class Parser(object):
    def __init__(self, tokens, template=None):
        self.tokens = tokens
        self.pos = 0
        self.template = template

    def error(self, message, line=None):
        raise TplError(message, line=line, template=self.template)

    # -- entry point ------------------------------------------------------

    def parse(self):
        body, end = self.parse_body(())
        if end is not None:  # pragma: no cover - parse_body consumes stops
            self.error("unexpected tag", end.line)
        return body

    # -- generic body parsing ----------------------------------------------

    def parse_body(self, stop_tags):
        """Parse nodes until EOF or a tag whose head is in ``stop_tags``.

        Returns ``(nodes, stop_token_or_None)``. The stop token is NOT
        consumed.
        """
        result = []
        while self.pos < len(self.tokens):
            tok = self.tokens[self.pos]
            if tok.kind == "text":
                result.append(ast_nodes.TextNode(tok.value))
                self.pos += 1
            elif tok.kind == "var":
                expr, filters = parse_output(tok.value, tok.line)
                result.append(ast_nodes.OutputNode(expr, filters, tok.line))
                self.pos += 1
            else:  # statement tag
                head = tok.value.split(None, 1)[0] if tok.value else ""
                if head in stop_tags:
                    return result, tok
                self.pos += 1
                result.append(self.parse_statement(tok, head))
        return result, None

    # -- statements ---------------------------------------------------------

    def parse_statement(self, tok, head):
        rest = tok.value[len(head):].strip()
        if head == "if":
            return self.parse_if(tok, rest)
        if head == "for":
            return self.parse_for(tok, rest)
        if head == "block":
            return self.parse_block(tok, rest)
        if head == "extends":
            if not rest:
                self.error("{% extends %} requires a template name", tok.line)
            return ast_nodes.ExtendsNode(parse_expression(rest, tok.line), tok.line)
        if head == "include":
            if not rest:
                self.error("{% include %} requires a template name", tok.line)
            return ast_nodes.IncludeNode(parse_expression(rest, tok.line), tok.line)
        if head in _END_TAGS:
            self.error("unexpected tag '{%% %s %%}' without matching opening tag" % head, tok.line)
        if not head:
            self.error("empty statement tag", tok.line)
        self.error("unknown tag: %r" % head, tok.line)

    def parse_if(self, tok, rest):
        if not rest:
            self.error("{% if %} requires a condition", tok.line)
        branches = []
        else_body = None
        cond = parse_expression(rest, tok.line)
        while True:
            body, end = self.parse_body(("elif", "else", "endif"))
            branches.append((cond, body))
            if end is None:
                self.error(
                    "unclosed {% if %}: expected {% endif %}", tok.line
                )
            self.pos += 1  # consume the stop token
            head = end.value.split(None, 1)[0]
            tail = end.value[len(head):].strip()
            if head == "elif":
                if not tail:
                    self.error("{% elif %} requires a condition", end.line)
                cond = parse_expression(tail, end.line)
                continue
            if head == "else":
                if tail:
                    self.error("{% else %} takes no arguments", end.line)
                else_body, end2 = self.parse_body(("endif",))
                if end2 is None:
                    self.error(
                        "unclosed {% if %}: expected {% endif %}", tok.line
                    )
                self.pos += 1
            break
        return ast_nodes.IfNode(branches, else_body)

    def parse_for(self, tok, rest):
        m = _FOR_RE.match(rest)
        if m is None:
            self.error(
                "malformed {% for %}: expected 'for <name> in <expression>'",
                tok.line,
            )
        var_name, expr_src = m.group(1), m.group(2)
        iter_expr = parse_expression(expr_src, tok.line)
        body, end = self.parse_body(("endfor",))
        if end is None:
            self.error("unclosed {% for %}: expected {% endfor %}", tok.line)
        self.pos += 1
        if end.value[len("endfor"):].strip():
            self.error("{% endfor %} takes no arguments", end.line)
        return ast_nodes.ForNode(var_name, iter_expr, body, tok.line)

    def parse_block(self, tok, rest):
        if not _NAME_RE.match(rest or ""):
            self.error(
                "{% block %} requires a valid block name, got %r" % rest,
                tok.line,
            )
        body, end = self.parse_body(("endblock",))
        if end is None:
            self.error(
                "unclosed {%% block %s %%}: expected {%% endblock %%}" % rest,
                tok.line,
            )
        self.pos += 1
        tail = end.value[len("endblock"):].strip()
        if tail and tail != rest:
            self.error(
                "endblock name %r does not match block name %r" % (tail, rest),
                end.line,
            )
        return ast_nodes.BlockNode(rest, body, tok.line)


def parse(tokens, template=None):
    return Parser(tokens, template).parse()
