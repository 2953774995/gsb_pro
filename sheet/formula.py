"""A small recursive-descent formula parser and evaluator (no ``eval``)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Protocol

from .model import (
    CellAddress,
    CellError,
    DivByZeroError,
    TypeErrorValue,
    col_index_to_letter,
    parse_address,
)

FUNCTIONS = {"SUM", "AVG", "MIN", "MAX", "COUNT", "AVERAGE"}


class FormulaSyntaxError(ValueError):
    """Raised while parsing an invalid formula."""


@dataclass(frozen=True)
class Number:
    value: float


@dataclass(frozen=True)
class Text:
    value: str


@dataclass(frozen=True)
class Boolean:
    value: bool


@dataclass(frozen=True)
class Reference:
    addr: CellAddress


@dataclass(frozen=True)
class Range:
    start: CellAddress
    end: CellAddress


@dataclass(frozen=True)
class Unary:
    op: str
    operand: object


@dataclass(frozen=True)
class Binary:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class FunctionCall:
    name: str
    args: tuple[object, ...]


Node = object


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    pos: int


class Lookup(Protocol):
    def __call__(self, addr: CellAddress) -> object: ...


@dataclass
class Evaluator:
    lookup: Lookup

    def eval(self, node: object) -> object:
        if isinstance(node, Number):
            return node.value
        if isinstance(node, Text):
            return node.value
        if isinstance(node, Boolean):
            return node.value
        if isinstance(node, Reference):
            value = self.lookup(node.addr)
            # A scalar reference to an empty cell is treated as zero.
            return 0.0 if value is None else value
        if isinstance(node, Range):
            # A bare range does not denote a scalar; supported functions
            # explicitly expand it.
            return TypeErrorValue("a range cannot be used outside a function")
        if isinstance(node, Unary):
            value = self.eval(node.operand)
            if isinstance(value, CellError):
                return value
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return TypeErrorValue("unary - requires a number")
            return -value if node.op == "-" else +value
        if isinstance(node, Binary):
            return self.eval_binary(node)
        if isinstance(node, FunctionCall):
            return self.eval_function(node)
        return TypeErrorValue("unknown expression")

    def eval_binary(self, node: Binary) -> object:
        # Short-circuit is unnecessary for this language, but error propagation
        # must evaluate both sides to catch bad references in each branch.
        left = self.eval(node.left)
        right = self.eval(node.right)
        if isinstance(left, CellError):
            return left
        if isinstance(right, CellError):
            return right

        if node.op == "&":
            from .model import display_value

            return display_value(left) + display_value(right)

        if node.op in ("=", "<>", "!=", "<", "<=", ">", ">="):
            return compare(node.op, left, right)

        if not isinstance(left, (int, float)) or isinstance(left, bool):
            return TypeErrorValue(f"{node.op} requires numbers")
        if not isinstance(right, (int, float)) or isinstance(right, bool):
            return TypeErrorValue(f"{node.op} requires numbers")
        if node.op == "+":
            return left + right
        if node.op == "-":
            return left - right
        if node.op == "*":
            return left * right
        if node.op == "/":
            if right == 0:
                return DivByZeroError("division by zero")
            return left / right
        return TypeErrorValue(f"unsupported operator {node.op}")

    def eval_function(self, call: FunctionCall) -> object:
        values: list[object] = []
        for arg in call.args:
            if isinstance(arg, Range):
                for row in range(arg.start.row, arg.end.row + 1):
                    for col in range(arg.start.col, arg.end.col + 1):
                        values.append(self.lookup(CellAddress(col, row)))
            else:
                value = self.eval(arg)
                if isinstance(value, CellError):
                    return value
                values.append(value)

        name = "AVG" if call.name == "AVERAGE" else call.name
        if name == "SUM":
            return sum_numbers(values)
        if name == "COUNT":
            return sum(1 for v in values if isinstance(v, (int, float)) and not isinstance(v, bool))
        if name == "AVG":
            total = sum_numbers(values)
            if isinstance(total, CellError):
                return total
            count = sum(1 for v in values if isinstance(v, (int, float)) and not isinstance(v, bool))
            if count == 0:
                return DivByZeroError("AVG of no numeric values")
            return total / count

        numeric = [
            float(v)
            for v in values
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        ]
        if any(
            v is not None
            and not (isinstance(v, (int, float)) and not isinstance(v, bool))
            for v in values
        ):
            return TypeErrorValue(f"{name} requires numeric values")
        if not numeric:
            return TypeErrorValue(f"{name} requires at least one value")
        if name == "MIN":
            return min(numeric)
        if name == "MAX":
            return max(numeric)
        return TypeErrorValue(f"unknown function {call.name}")


def sum_numbers(values: list[object]) -> object:
    total = 0.0
    for value in values:
        if value is None:
            continue
        if isinstance(value, CellError):
            return value
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return TypeErrorValue("SUM requires numeric values")
        total += float(value)
    return total


def compare(op: str, left: object, right: object) -> object:
    if isinstance(left, bool) or isinstance(right, bool):
        if not isinstance(left, bool) or not isinstance(right, bool):
            return TypeErrorValue("cannot compare logical and non-logical values")
        l, r = left, right
    elif isinstance(left, (int, float)) and isinstance(right, (int, float)):
        l, r = float(left), float(right)
    elif isinstance(left, str) and isinstance(right, str):
        l, r = left, right
    else:
        return TypeErrorValue("operands must have comparable types")

    if op == "=":
        return l == r
    if op in ("<>", "!="):
        return l != r
    if op == "<":
        return l < r
    if op == "<=":
        return l <= r
    if op == ">":
        return l > r
    if op == ">=":
        return l >= r
    return TypeErrorValue(f"unsupported comparison {op}")


_TOKEN_RE = re.compile(
    r"""
    \s*(?:
        (?P<number>\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?
      | (?P<string>"(?:[^"]|"")*")
      | (?P<identifier>[A-Za-z]+[0-9]*)
      | (?P<op><=|>=|<>|!=|[+\-*/()=,:<>&])
    )
    """,
    re.VERBOSE,
)


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if not match or match.end() == pos:
            raise FormulaSyntaxError(f"unexpected character at position {pos}: {text[pos:]!r}")
        pos = match.end()
        for kind in ("number", "string", "identifier", "op"):
            value = match.group(kind)
            if value is not None:
                tokens.append(Token(kind, value, match.start()))
                break
    tokens.append(Token("eof", "", len(text)))
    return tokens


class Parser:
    def __init__(self, expression: str) -> None:
        self.expression = expression
        self.tokens = tokenize(expression)
        self.pos = 0

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def take(self) -> Token:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def expect(self, value: str) -> Token:
        token = self.take()
        if token.value != value:
            raise FormulaSyntaxError(f"expected {value!r} at position {token.pos}")
        return token

    def parse(self) -> Node:
        node = self.parse_comparison()
        if self.peek().kind != "eof":
            token = self.peek()
            raise FormulaSyntaxError(f"unexpected token {token.value!r} at position {token.pos}")
        return node

    def parse_comparison(self) -> Node:
        node = self.parse_concat()
        while self.peek().value in ("=", "<>", "!=", "<", "<=", ">", ">="):
            op = self.take().value
            node = Binary(op, node, self.parse_concat())
        return node

    def parse_concat(self) -> Node:
        node = self.parse_additive()
        while self.peek().value == "&":
            self.take()
            node = Binary("&", node, self.parse_additive())
        return node

    def parse_additive(self) -> Node:
        node = self.parse_multiplicative()
        while self.peek().value in ("+", "-"):
            op = self.take().value
            node = Binary(op, node, self.parse_multiplicative())
        return node

    def parse_multiplicative(self) -> Node:
        node = self.parse_unary()
        while self.peek().value in ("*", "/"):
            op = self.take().value
            node = Binary(op, node, self.parse_unary())
        return node

    def parse_unary(self) -> Node:
        if self.peek().value in ("+", "-"):
            op = self.take().value
            return Unary(op, self.parse_unary())
        return self.parse_primary()

    def parse_primary(self) -> Node:
        token = self.peek()
        if token.kind == "number":
            self.take()
            return Number(float(token.value))
        if token.kind == "string":
            self.take()
            return Text(unescape_string(token.value))
        if token.value == "(":
            self.take()
            node = self.parse_comparison()
            self.expect(")")
            return self.maybe_range(node)
        if token.kind == "identifier":
            return self.parse_identifier()
        raise FormulaSyntaxError(f"expected a value at position {token.pos}")

    def parse_identifier(self) -> Node:
        token = self.take()
        upper = token.value.upper()
        if upper in ("TRUE", "FALSE"):
            return Boolean(upper == "TRUE")
        if re.fullmatch(r"[A-Z]+[0-9]+", upper):
            return self.maybe_range(Reference(parse_address(upper)))
        if self.peek().value == "(":
            return self.parse_function(upper)
        raise FormulaSyntaxError(f"unknown identifier {token.value!r}")

    def parse_function(self, name: str) -> Node:
        self.expect("(")
        args: list[Node] = []
        if self.peek().value != ")":
            while True:
                args.append(self.parse_comparison())
                if self.peek().value != ",":
                    break
                self.take()
        self.expect(")")
        return FunctionCall(name, tuple(args))

    def maybe_range(self, node: Node) -> Node:
        if self.peek().value == ":":
            if not isinstance(node, Reference):
                token = self.take()
                raise FormulaSyntaxError(f"range must start with a cell at position {token.pos}")
            self.take()
            end_token = self.peek()
            end = self.parse_primary()
            if not isinstance(end, Reference):
                raise FormulaSyntaxError(f"range must end with a cell at position {end_token.pos}")
            start = normalize_ref(node.addr)
            end_addr = normalize_ref(end.addr)
            return Range(
                CellAddress(min(start.col, end_addr.col), min(start.row, end_addr.row)),
                CellAddress(max(start.col, end_addr.col), max(start.row, end_addr.row)),
            )
        return node


def normalize_ref(addr: CellAddress) -> CellAddress:
    return CellAddress(addr.col, addr.row)


def unescape_string(raw: str) -> str:
    return raw[1:-1].replace('""', '"')


def parse_formula(text: str) -> Node:
    if not text.startswith("="):
        raise FormulaSyntaxError("formula must start with '='")
    parser = Parser(text[1:])
    return parser.parse()


def node_references(node: object) -> list[tuple[CellAddress, CellAddress | None]]:
    """Return (cell, range_end) dependencies; range_end is None for one cell."""
    refs: list[tuple[CellAddress, CellAddress | None]] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, Reference):
            refs.append((current.addr, None))
        elif isinstance(current, Range):
            refs.append((current.start, current.end))
        elif isinstance(current, Unary):
            stack.append(current.operand)
        elif isinstance(current, Binary):
            stack.extend((current.right, current.left))
        elif isinstance(current, FunctionCall):
            stack.extend(current.args)
    return refs


def describe_ast(node: object) -> str:
    """Small AST text used primarily in tests/debugging."""
    if isinstance(node, Number):
        return str(node.value)
    if isinstance(node, Text):
        return repr(node.value)
    if isinstance(node, Boolean):
        return "TRUE" if node.value else "FALSE"
    if isinstance(node, Reference):
        return str(node.addr)
    if isinstance(node, Range):
        return f"{node.start}:{node.end}"
    if isinstance(node, Unary):
        return f"(-{describe_ast(node.operand)})"
    if isinstance(node, Binary):
        return f"({describe_ast(node.left)} {node.op} {describe_ast(node.right)})"
    if isinstance(node, FunctionCall):
        return f"{node.name}({', '.join(describe_ast(a) for a in node.args)})"
    return "?"


def format_addr(addr: CellAddress) -> str:
    return f"{col_index_to_letter(addr.col)}{addr.row}"
