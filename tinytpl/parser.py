"""把 token 流解析为模板 AST，并收集 extends / blocks 元数据。"""

import re

from .errors import TplError
from .expr import parse_expression
from . import nodes
from .tokenizer import TEXT, VAR, TAG

_FOR_RE = re.compile(r"^for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+(.+)$", re.S)
_BLOCK_RE = re.compile(r"^block\s+([A-Za-z_][A-Za-z0-9_]*)$")
_ENDBLOCK_RE = re.compile(r"^endblock(?:\s+([A-Za-z_][A-Za-z0-9_]*))?$")

_END_TAGS = ("endif", "elif", "else", "endfor", "endblock")


class Parser(object):
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self.depth = 0
        self.extends = None
        self.blocks = {}

    def parse(self):
        body, _, _ = self._parse_until(())
        return body

    # ------------------------------------------------------------ 核心循环

    def _parse_until(self, end_tags):
        """解析直到遇到 end_tags 中的某个标签（不消费该标签）。"""
        result = []
        while self.pos < len(self.tokens):
            tok = self.tokens[self.pos]
            if tok.type == TEXT:
                result.append(nodes.TextNode(tok.content, tok.lineno))
                self.pos += 1
            elif tok.type == VAR:
                result.append(self._parse_var(tok))
                self.pos += 1
            else:  # TAG
                head = tok.content.split(None, 1)[0] if tok.content else ""
                if head in end_tags:
                    return result, head, tok
                if head in _END_TAGS:
                    raise TplError(
                        "unexpected tag %r at line %d"
                        % (head, tok.lineno))
                handler = getattr(self, "_tag_" + head, None)
                if handler is None:
                    raise TplError(
                        "unknown tag %r at line %d"
                        % (head or tok.content, tok.lineno))
                node = handler(tok)
                if node is not None:
                    result.append(node)
        if end_tags:
            raise TplError(
                "unexpected end of template, expected %s"
                % " or ".join("{%% %s %%}" % t for t in end_tags))
        return result, None, None

    def _nested(self, end_tags):
        self.depth += 1
        try:
            return self._parse_until(end_tags)
        finally:
            self.depth -= 1

    # ------------------------------------------------------------ 各类标签

    def _parse_var(self, tok):
        expr = parse_expression(tok.content, tok.lineno)
        raw = getattr(expr, "filters", None) == ["raw"]
        return nodes.VarNode(expr, raw, tok.lineno)

    def _tag_if(self, tok):
        cond_src = tok.content[len("if"):].strip()
        if not cond_src:
            raise TplError("if tag requires a condition at line %d"
                           % tok.lineno)
        branches = [(parse_expression(cond_src, tok.lineno), None)]
        self.pos += 1
        body, end, end_tok = self._nested(("elif", "else", "endif"))
        branches[0] = (branches[0][0], body)
        else_body = []
        while end == "elif":
            cond_src = end_tok.content[len("elif"):].strip()
            if not cond_src:
                raise TplError("elif tag requires a condition at line %d"
                               % end_tok.lineno)
            cond = parse_expression(cond_src, end_tok.lineno)
            self.pos += 1
            body, end, end_tok = self._nested(("elif", "else", "endif"))
            branches.append((cond, body))
        if end == "else":
            if end_tok.content != "else":
                raise TplError("else tag takes no arguments at line %d"
                               % end_tok.lineno)
            self.pos += 1
            else_body, end, end_tok = self._nested(("endif",))
        # 此时 end 必为 endif
        if end_tok.content != "endif":
            raise TplError("endif tag takes no arguments at line %d"
                           % end_tok.lineno)
        self.pos += 1
        return nodes.IfNode(branches, else_body, tok.lineno)

    def _tag_for(self, tok):
        m = _FOR_RE.match(tok.content)
        if not m:
            raise TplError(
                "malformed for tag (expected 'for x in items') "
                "at line %d" % tok.lineno)
        var_name, iter_src = m.group(1), m.group(2)
        iter_expr = parse_expression(iter_src, tok.lineno)
        self.pos += 1
        body, _, end_tok = self._nested(("endfor",))
        if end_tok.content != "endfor":
            raise TplError("endfor tag takes no arguments at line %d"
                           % end_tok.lineno)
        self.pos += 1
        return nodes.ForNode(var_name, iter_expr, body, tok.lineno)

    def _tag_block(self, tok):
        m = _BLOCK_RE.match(tok.content)
        if not m:
            raise TplError(
                "malformed block tag (expected 'block name') at line %d"
                % tok.lineno)
        name = m.group(1)
        if name in self.blocks:
            raise TplError(
                "duplicate block name %r at line %d" % (name, tok.lineno))
        self.pos += 1
        body, _, end_tok = self._nested(("endblock",))
        m2 = _ENDBLOCK_RE.match(end_tok.content)
        if not m2:
            raise TplError("malformed endblock tag at line %d"
                           % end_tok.lineno)
        if m2.group(1) is not None and m2.group(1) != name:
            raise TplError(
                "endblock name %r does not match block %r at line %d"
                % (m2.group(1), name, end_tok.lineno))
        self.pos += 1
        node = nodes.BlockNode(name, body, tok.lineno)
        self.blocks[name] = node
        return node

    def _tag_extends(self, tok):
        if self.depth > 0:
            raise TplError(
                "extends must be a top-level tag at line %d" % tok.lineno)
        if self.extends is not None:
            raise TplError(
                "multiple extends tags at line %d" % tok.lineno)
        for prev in self.tokens[:self.pos]:
            if prev.type != TEXT or prev.content.strip():
                raise TplError(
                    "extends must be the first tag in the template "
                    "at line %d" % tok.lineno)
        name_src = tok.content[len("extends"):].strip()
        if not name_src:
            raise TplError("extends requires a template name at line %d"
                           % tok.lineno)
        self.extends = nodes.ExtendsNode(
            parse_expression(name_src, tok.lineno), tok.lineno)
        self.pos += 1
        return None  # extends 不产生输出节点

    def _tag_include(self, tok):
        name_src = tok.content[len("include"):].strip()
        if not name_src:
            raise TplError("include requires a template name at line %d"
                           % tok.lineno)
        self.pos += 1
        return nodes.IncludeNode(
            parse_expression(name_src, tok.lineno), tok.lineno)


def parse(tokens):
    """解析 token 流，返回 (nodes, extends_node, blocks_dict)。"""
    parser = Parser(tokens)
    body = parser.parse()
    return body, parser.extends, parser.blocks
