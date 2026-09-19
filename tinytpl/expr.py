"""表达式解析与求值。

支持：变量、字符串/数字/布尔/None 字面量、点号取值（user.name、items.0）、
比较（== != < <= > >=）、逻辑（and or not）、算术（+ - * / // %）、括号、
以及 `| raw` 过滤器（仅在 {{ }} 输出时有意义）。
"""

import ast
import operator
import re

from .errors import TplError

# ---------------------------------------------------------------- 词法分析

_TOKEN_SPEC = [
    ("NUMBER", r"\d+(?:\.\d+)?"),
    ("STRING", r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\""),
    ("NAME", r"[A-Za-z_][A-Za-z0-9_]*"),
    ("OP", r"==|!=|<=|>=|//|[<>+\-*/%().,|]"),
    ("WS", r"\s+"),
]
_MASTER_RE = re.compile("|".join("(?P<%s>%s)" % s for s in _TOKEN_SPEC))

_CMP_OPS = {"==", "!=", "<", "<=", ">", ">="}
_KEYWORDS = {"and", "or", "not", "True", "False", "None"}


class _Tok(object):
    __slots__ = ("kind", "value")

    def __init__(self, kind, value):
        self.kind = kind
        self.value = value


def _lex(src, lineno):
    toks = []
    pos = 0
    while pos < len(src):
        m = _MASTER_RE.match(src, pos)
        if m is None:
            raise TplError(
                "invalid character %r in expression at line %d"
                % (src[pos], lineno))
        kind = m.lastgroup
        if kind != "WS":
            toks.append(_Tok(kind, m.group()))
        pos = m.end()
    return toks


# ---------------------------------------------------------------- AST 节点

class Expr(object):
    def eval(self, rc):  # pragma: no cover - 抽象接口
        raise NotImplementedError


class Literal(Expr):
    def __init__(self, value):
        self.value = value

    def eval(self, rc):
        return self.value


class Name(Expr):
    def __init__(self, name, lineno):
        self.name = name
        self.lineno = lineno

    def eval(self, rc):
        return rc.resolve(self.name, self.lineno)


class GetAttr(Expr):
    def __init__(self, obj, attr, lineno):
        self.obj = obj
        self.attr = attr
        self.lineno = lineno

    def eval(self, rc):
        return rc.get_attr(self.obj.eval(rc), self.attr, self.lineno)


class UnaryOp(Expr):
    def __init__(self, op, operand, lineno):
        self.op = op
        self.operand = operand
        self.lineno = lineno

    def eval(self, rc):
        value = self.operand.eval(rc)
        if self.op == "not":
            return not _truthy(value)
        try:
            if self.op == "-":
                return -value
            return +value
        except TypeError:
            raise TplError(
                "bad operand type for unary %r at line %d"
                % (self.op, self.lineno))


_BIN_OPS = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "/": operator.truediv,
    "//": operator.floordiv,
    "%": operator.mod,
}


class BinOp(Expr):
    def __init__(self, op, left, right, lineno):
        self.op = op
        self.left = left
        self.right = right
        self.lineno = lineno

    def eval(self, rc):
        left = self.left.eval(rc)
        right = self.right.eval(rc)
        try:
            return _BIN_OPS[self.op](left, right)
        except ZeroDivisionError:
            raise TplError("division by zero at line %d" % self.lineno)
        except TypeError:
            raise TplError(
                "unsupported operand types for %r: %r and %r at line %d"
                % (self.op, type(left).__name__,
                   type(right).__name__, self.lineno))


class Compare(Expr):
    """支持 Python 风格的链式比较：a < b <= c。"""

    def __init__(self, first, ops, rest, lineno):
        self.first = first
        self.ops = ops
        self.rest = rest
        self.lineno = lineno

    def eval(self, rc):
        left = self.first.eval(rc)
        for op, right_expr in zip(self.ops, self.rest):
            right = right_expr.eval(rc)
            try:
                if op == "==":
                    ok = left == right
                elif op == "!=":
                    ok = left != right
                elif op == "<":
                    ok = left < right
                elif op == "<=":
                    ok = left <= right
                elif op == ">":
                    ok = left > right
                else:
                    ok = left >= right
            except TypeError:
                raise TplError(
                    "cannot compare %r and %r at line %d"
                    % (type(left).__name__, type(right).__name__,
                       self.lineno))
            if not ok:
                return False
            left = right
        return True


class BoolOp(Expr):
    def __init__(self, op, values):
        self.op = op
        self.values = values

    def eval(self, rc):
        if self.op == "and":
            result = True
            for expr in self.values:
                result = expr.eval(rc)
                if not _truthy(result):
                    return result
            return result
        result = False
        for expr in self.values:
            result = expr.eval(rc)
            if _truthy(result):
                return result
        return result


class Filtered(Expr):
    """expr | filter —— 目前仅支持 raw（对求值无影响，只影响输出转义）。"""

    def __init__(self, expr, filters, lineno):
        self.expr = expr
        self.filters = filters
        self.lineno = lineno

    def eval(self, rc):
        return self.expr.eval(rc)


def _truthy(value):
    return bool(value)


# ---------------------------------------------------------------- 语法分析

class _Parser(object):
    def __init__(self, toks, lineno):
        self.toks = toks
        self.pos = 0
        self.lineno = lineno

    # -- 工具 --
    def _peek(self):
        if self.pos < len(self.toks):
            return self.toks[self.pos]
        return None

    def _error(self, msg):
        raise TplError("%s at line %d" % (msg, self.lineno))

    def _accept_op(self, op):
        tok = self._peek()
        if tok is not None and tok.kind == "OP" and tok.value == op:
            self.pos += 1
            return True
        return False

    def _accept_name(self, name):
        tok = self._peek()
        if tok is not None and tok.kind == "NAME" and tok.value == name:
            self.pos += 1
            return True
        return False

    def _expect_op(self, op):
        if not self._accept_op(op):
            self._error("expected %r in expression" % op)

    # -- 文法（优先级从低到高）--
    def parse_or(self):
        values = [self.parse_and()]
        while self._accept_name("or"):
            values.append(self.parse_and())
        if len(values) == 1:
            return values[0]
        return BoolOp("or", values)

    def parse_and(self):
        values = [self.parse_not()]
        while self._accept_name("and"):
            values.append(self.parse_not())
        if len(values) == 1:
            return values[0]
        return BoolOp("and", values)

    def parse_not(self):
        if self._accept_name("not"):
            return UnaryOp("not", self.parse_not(), self.lineno)
        return self.parse_comparison()

    def parse_comparison(self):
        first = self.parse_arith()
        ops = []
        rest = []
        while True:
            tok = self._peek()
            if tok is not None and tok.kind == "OP" and tok.value in _CMP_OPS:
                ops.append(tok.value)
                self.pos += 1
                rest.append(self.parse_arith())
            else:
                break
        if not ops:
            return first
        return Compare(first, ops, rest, self.lineno)

    def parse_arith(self):
        left = self.parse_term()
        while True:
            if self._accept_op("+"):
                left = BinOp("+", left, self.parse_term(), self.lineno)
            elif self._accept_op("-"):
                left = BinOp("-", left, self.parse_term(), self.lineno)
            else:
                return left

    def parse_term(self):
        left = self.parse_unary()
        while True:
            for op in ("*", "/", "//", "%"):
                if self._accept_op(op):
                    left = BinOp(op, left, self.parse_unary(), self.lineno)
                    break
            else:
                return left

    def parse_unary(self):
        if self._accept_op("-"):
            return UnaryOp("-", self.parse_unary(), self.lineno)
        if self._accept_op("+"):
            return UnaryOp("+", self.parse_unary(), self.lineno)
        return self.parse_postfix()

    def parse_postfix(self):
        expr = self.parse_primary()
        while self._accept_op("."):
            tok = self._peek()
            if tok is None or tok.kind not in ("NAME", "NUMBER"):
                self._error("expected attribute name after '.'")
            self.pos += 1
            expr = GetAttr(expr, tok.value, self.lineno)
        return expr

    def parse_primary(self):
        tok = self._peek()
        if tok is None:
            self._error("unexpected end of expression")
        if tok.kind == "NUMBER":
            self.pos += 1
            return Literal(float(tok.value) if "." in tok.value
                           else int(tok.value))
        if tok.kind == "STRING":
            self.pos += 1
            try:
                return Literal(ast.literal_eval(tok.value))
            except (ValueError, SyntaxError):
                self._error("invalid string literal %r" % tok.value)
        if tok.kind == "NAME":
            self.pos += 1
            if tok.value == "True":
                return Literal(True)
            if tok.value == "False":
                return Literal(False)
            if tok.value == "None":
                return Literal(None)
            if tok.value in ("and", "or", "not"):
                self._error("unexpected keyword %r" % tok.value)
            return Name(tok.value, self.lineno)
        if tok.kind == "OP" and tok.value == "(":
            self.pos += 1
            expr = self.parse_or()
            self._expect_op(")")
            return expr
        self._error("unexpected token %r" % tok.value)


def parse_expression(src, lineno=0):
    """把表达式源码解析为 Expr 树，可带 `| raw` 过滤器。"""
    if not src or not src.strip():
        raise TplError("empty expression at line %d" % lineno)
    parser = _Parser(_lex(src, lineno), lineno)
    expr = parser.parse_or()
    filters = []
    while parser._accept_op("|"):
        tok = parser._peek()
        if tok is None or tok.kind != "NAME":
            parser._error("expected filter name after '|'")
        parser.pos += 1
        if tok.value != "raw":
            raise TplError(
                "unknown filter %r at line %d" % (tok.value, lineno))
        filters.append(tok.value)
    if parser.pos != len(parser.toks):
        parser._error("unexpected token %r"
                      % parser.toks[parser.pos].value)
    if filters:
        return Filtered(expr, filters, lineno)
    return expr
