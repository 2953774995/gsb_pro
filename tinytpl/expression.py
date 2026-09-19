"""Expression lexer, parser and evaluator.

Supports: variables, dotted access (``user.name``, ``items.0``),
string/number/boolean/None literals, comparisons (``== != < <= > >=``),
logic (``and or not``), arithmetic (``+ - * / // %``), unary +/- and
parentheses.  Output expressions may also use filters: ``{{ x | raw }}``.
"""

import ast
import re

from .errors import TplError

# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

_LEX_RE = re.compile(
    r"""
      (?P<number>\d+(?:\.\d+)?)
    | (?P<string>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
    | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<op>==|!=|<=|>=|//|[<>\+\-\*/%()\|.])
    | (?P<ws>\s+)
    """,
    re.VERBOSE,
)

_LITERAL_NAMES = {
    "true": True,
    "false": False,
    "none": None,
    "True": True,
    "False": False,
    "None": None,
}

_CMP_OPS = ("==", "!=", "<", "<=", ">", ">=")


class _Tok(object):
    __slots__ = ("kind", "value")

    def __init__(self, kind, value):
        self.kind = kind
        self.value = value

    def __repr__(self):  # pragma: no cover - debugging aid
        return "_Tok(%r, %r)" % (self.kind, self.value)


def _lex(source, line):
    tokens = []
    pos = 0
    while pos < len(source):
        m = _LEX_RE.match(source, pos)
        if m is None:
            raise TplError(
                "unexpected character %r in expression" % source[pos], line=line
            )
        kind = m.lastgroup
        if kind != "ws":
            tokens.append(_Tok(kind, m.group()))
        pos = m.end()
    return tokens


# ---------------------------------------------------------------------------
# Parser (recursive descent).  Produces tuple trees:
#   ('lit', value) ('name', n) ('attr', base, seg)
#   ('bin', op, l, r) ('neg', x) ('not', x)
#   ('or', a, b) ('and', a, b) ('cmp', first, [(op, node), ...])
# ---------------------------------------------------------------------------


class _Parser(object):
    def __init__(self, tokens, line):
        self.tokens = tokens
        self.pos = 0
        self.line = line

    def error(self, msg):
        raise TplError(msg, line=self.line)

    def peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def next(self):
        tok = self.peek()
        if tok is None:
            self.error("unexpected end of expression")
        self.pos += 1
        return tok

    def accept_op(self, *values):
        tok = self.peek()
        if tok is not None and tok.kind == "op" and tok.value in values:
            self.pos += 1
            return tok.value
        return None

    def accept_name(self, *values):
        tok = self.peek()
        if tok is not None and tok.kind == "name" and tok.value in values:
            self.pos += 1
            return tok.value
        return None

    def expect_op(self, value):
        got = self.accept_op(value)
        if got is None:
            tok = self.peek()
            found = "end of expression" if tok is None else repr(tok.value)
            self.error("expected %r, found %s" % (value, found))

    # or_expr := and_expr ( 'or' and_expr )*
    def parse_or(self):
        node = self.parse_and()
        while self.accept_name("or"):
            node = ("or", node, self.parse_and())
        return node

    # and_expr := not_expr ( 'and' not_expr )*
    def parse_and(self):
        node = self.parse_not()
        while self.accept_name("and"):
            node = ("and", node, self.parse_not())
        return node

    # not_expr := 'not' not_expr | comparison
    def parse_not(self):
        if self.accept_name("not"):
            return ("not", self.parse_not())
        return self.parse_comparison()

    # comparison := arith ( cmpop arith )*
    def parse_comparison(self):
        first = self.parse_arith()
        rest = []
        while True:
            tok = self.peek()
            if tok is not None and tok.kind == "op" and tok.value in _CMP_OPS:
                self.pos += 1
                rest.append((tok.value, self.parse_arith()))
            else:
                break
        if rest:
            return ("cmp", first, rest)
        return first

    # arith := term ( ('+'|'-') term )*
    def parse_arith(self):
        node = self.parse_term()
        while True:
            op = self.accept_op("+", "-")
            if op is None:
                return node
            node = ("bin", op, node, self.parse_term())

    # term := unary ( ('*'|'/'|'//'|'%') unary )*
    def parse_term(self):
        node = self.parse_unary()
        while True:
            op = self.accept_op("*", "/", "//", "%")
            if op is None:
                return node
            node = ("bin", op, node, self.parse_unary())

    # unary := ('-'|'+') unary | postfix
    def parse_unary(self):
        op = self.accept_op("-", "+")
        if op == "-":
            return ("neg", self.parse_unary())
        if op == "+":
            return self.parse_unary()
        return self.parse_postfix()

    # postfix := primary ( '.' (name|number) )*
    def parse_postfix(self):
        node = self.parse_primary()
        while self.accept_op("."):
            tok = self.next()
            if tok.kind not in ("name", "number"):
                self.error("expected attribute name after '.'")
            node = ("attr", node, tok.value)
        return node

    # primary := number | string | name | '(' or_expr ')'
    def parse_primary(self):
        tok = self.next()
        if tok.kind == "number":
            value = float(tok.value) if "." in tok.value else int(tok.value)
            return ("lit", value)
        if tok.kind == "string":
            try:
                return ("lit", ast.literal_eval(tok.value))
            except (SyntaxError, ValueError):
                self.error("invalid string literal %s" % tok.value)
        if tok.kind == "name":
            if tok.value in _LITERAL_NAMES:
                return ("lit", _LITERAL_NAMES[tok.value])
            if tok.value in ("and", "or", "not"):
                self.error("unexpected keyword %r" % tok.value)
            return ("name", tok.value)
        if tok.kind == "op" and tok.value == "(":
            node = self.parse_or()
            self.expect_op(")")
            return node
        self.error("unexpected token %r" % tok.value)


def parse_expression(source, line=None):
    """Parse an expression string into a tuple tree."""
    if not source or not source.strip():
        raise TplError("empty expression", line=line)
    parser = _Parser(_lex(source, line), line)
    node = parser.parse_or()
    leftover = parser.peek()
    if leftover is not None:
        parser.error("unexpected token %r" % leftover.value)
    return node


def parse_output(source, line=None):
    """Parse an output expression ``expr | filter | ...``.

    Returns ``(expr_node, [filter_names])``.
    """
    if not source or not source.strip():
        raise TplError("empty expression in {{ }}", line=line)
    parser = _Parser(_lex(source, line), line)
    node = parser.parse_or()
    filters = []
    while parser.accept_op("|"):
        tok = parser.next()
        if tok.kind != "name":
            parser.error("expected filter name after '|'")
        filters.append(tok.value)
    leftover = parser.peek()
    if leftover is not None:
        parser.error("unexpected token %r" % leftover.value)
    return node, filters


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

_BIN_OPS = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": lambda a, b: a / b,
    "//": lambda a, b: a // b,
    "%": lambda a, b: a % b,
}

_CMP_FUNCS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}


def eval_expr(node, ctx):
    """Evaluate a parsed expression tree against a render context."""
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "name":
        return ctx.resolve(node[1])
    if kind == "attr":
        return ctx.get_attr(eval_expr(node[1], ctx), node[2])
    if kind == "or":
        left = eval_expr(node[1], ctx)
        return left if left else eval_expr(node[2], ctx)
    if kind == "and":
        left = eval_expr(node[1], ctx)
        return eval_expr(node[2], ctx) if left else left
    if kind == "not":
        return not eval_expr(node[1], ctx)
    if kind == "neg":
        return -eval_expr(node[1], ctx)
    if kind == "bin":
        left = eval_expr(node[2], ctx)
        right = eval_expr(node[3], ctx)
        try:
            return _BIN_OPS[node[1]](left, right)
        except TplError:
            raise
        except Exception as exc:
            raise TplError(
                "cannot compute %r %s %r: %s" % (left, node[1], right, exc)
            )
    if kind == "cmp":
        left = eval_expr(node[1], ctx)
        for op, sub in node[2]:
            right = eval_expr(sub, ctx)
            try:
                ok = _CMP_FUNCS[op](left, right)
            except TplError:
                raise
            except Exception as exc:
                raise TplError(
                    "cannot compare %r %s %r: %s" % (left, op, right, exc)
                )
            if not ok:
                return False
            left = right
        return True
    raise TplError("unknown expression node %r" % (kind,))  # pragma: no cover
