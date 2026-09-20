"""公式词法分析、递归下降解析和引用收集。

支持：
- 数字、文本、TRUE/FALSE
- + - * /、括号、一元正负号
- 比较运算 < <= > >= = <>
- 字符串拼接 &
- 单元格、A1:B2 区域和 SUM/AVG/AVERAGE/MIN/MAX/COUNT
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from .address import Range, split_address


class FormulaSyntaxError(Exception):
    """公式语法错误。"""


# AST 使用简单的不可变 dataclass，避免引入 eval 或外部解析库。
@dataclass(frozen=True)
class Number:
    value: float | int


@dataclass(frozen=True)
class Text:
    value: str


@dataclass(frozen=True)
class Boolean:
    value: bool


@dataclass(frozen=True)
class Ref:
    row: int
    col: int
    address: str


@dataclass(frozen=True)
class RangeRef:
    cell_range: Range


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
class Call:
    name: str
    args: tuple[object, ...]


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    pos: int


_NUMBER_RE = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_IDENT_RE = re.compile(r"[A-Za-z]+")
_CELL_RE = re.compile(r"[A-Za-z]+\d+")


def tokenize(formula: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    while i < len(formula):
        char = formula[i]
        if char.isspace():
            i += 1
            continue

        if char == '"':
            start = i
            i += 1
            chars: list[str] = []
            closed = False
            while i < len(formula):
                ch = formula[i]
                if ch == '"':
                    if i + 1 < len(formula) and formula[i + 1] == '"':
                        chars.append('"')
                        i += 2
                        continue
                    i += 1
                    closed = True
                    break
                chars.append(ch)
                i += 1
            if not closed:
                raise FormulaSyntaxError("字符串缺少结束引号")
            tokens.append(Token("STRING", "".join(chars), start))
            continue

        two = formula[i : i + 2]
        if two in ("<=", ">=", "<>"):
            tokens.append(Token("OP", two, i))
            i += 2
            continue
        if char in "+-*/&<>=(),:":
            tokens.append(Token("OP", char, i))
            i += 1
            continue

        number = _NUMBER_RE.match(formula, i)
        if number:
            tokens.append(Token("NUMBER", number.group(0), i))
            i = number.end()
            continue

        # A1:B2 或 A1；这里先识别地址，避免函数名 SUM 被误当成列。
        cell = _CELL_RE.match(formula, i)
        if cell:
            text = cell.group(0)
            end = cell.end()
            try:
                row, col = split_address(text)
            except ValueError as exc:
                raise FormulaSyntaxError(str(exc)) from None
            if end < len(formula) and formula[end] == ":":
                second = _CELL_RE.match(formula, end + 1)
                if not second:
                    raise FormulaSyntaxError("区域引用冒号后必须是单元格地址")
                try:
                    cell_range = Range.parse(f"{text}:{second.group(0)}")
                except ValueError:
                    raise FormulaSyntaxError("区域终点不能小于起点") from None
                tokens.append(Token("RANGE", f"{cell_range.start_row},{cell_range.start_col},{cell_range.end_row},{cell_range.end_col}", i))
                i = second.end()
            else:
                tokens.append(Token("REF", f"{row},{col}", i))
                i = end
            continue

        ident = _IDENT_RE.match(formula, i)
        if ident:
            tokens.append(Token("IDENT", ident.group(0).upper(), i))
            i = ident.end()
            continue

        raise FormulaSyntaxError(f"无法识别的字符 {char!r}")

    tokens.append(Token("EOF", "", len(formula)))
    return tokens


class Parser:
    """优先级（低到高）：比较、&、加减、乘除、一元、原子。"""

    def __init__(self, formula: str):
        self.tokens = tokenize(formula)
        self.pos = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.pos]

    def eat(self, value: str | None = None, kind: str | None = None) -> Token:
        token = self.current
        if value is not None and token.value != value:
            raise FormulaSyntaxError(f"期望 {value!r}，实际为 {token.value!r}")
        if kind is not None and token.kind != kind:
            raise FormulaSyntaxError(f"期望 {kind}，实际为 {token.kind}")
        self.pos += 1
        return token

    def parse(self) -> object:
        node = self.parse_comparison()
        if self.current.kind != "EOF":
            raise FormulaSyntaxError(f"公式末尾有多余内容: {self.current.value!r}")
        return node

    def parse_comparison(self) -> object:
        node = self.parse_concat()
        while self.current.kind == "OP" and self.current.value in (
            "=",
            "<>",
            "<",
            "<=",
            ">",
            ">=",
        ):
            op = self.eat(kind="OP").value
            node = Binary(op, node, self.parse_concat())
        return node

    def parse_concat(self) -> object:
        node = self.parse_additive()
        while self.current.kind == "OP" and self.current.value == "&":
            self.eat("&")
            node = Binary("&", node, self.parse_additive())
        return node

    def parse_additive(self) -> object:
        node = self.parse_multiplicative()
        while self.current.kind == "OP" and self.current.value in ("+", "-"):
            op = self.eat(kind="OP").value
            node = Binary(op, node, self.parse_multiplicative())
        return node

    def parse_multiplicative(self) -> object:
        node = self.parse_unary()
        while self.current.kind == "OP" and self.current.value in ("*", "/"):
            op = self.eat(kind="OP").value
            node = Binary(op, node, self.parse_unary())
        return node

    def parse_unary(self) -> object:
        if self.current.kind == "OP" and self.current.value in ("+", "-"):
            op = self.eat(kind="OP").value
            return Unary(op, self.parse_unary())
        return self.parse_primary()

    def parse_primary(self) -> object:
        token = self.current

        if token.kind == "NUMBER":
            self.eat(kind="NUMBER")
            text = token.value
            value: int | float
            if "." not in text and "e" not in text.lower():
                value = int(text)
            else:
                value = float(text)
            return Number(value)

        if token.kind == "STRING":
            self.eat(kind="STRING")
            return Text(token.value)

        if token.kind == "REF":
            self.eat(kind="REF")
            row_text, col_text = token.value.split(",")
            row, col = int(row_text), int(col_text)
            from .address import join_address

            return Ref(row, col, join_address(row, col))

        if token.kind == "RANGE":
            self.eat(kind="RANGE")
            parts = token.value.split(",")
            coords = tuple(int(part) for part in parts)
            return RangeRef(Range(*coords))

        if token.kind == "IDENT":
            name = self.eat(kind="IDENT").value.upper()
            if name == "TRUE":
                return Boolean(True)
            if name == "FALSE":
                return Boolean(False)
            self.eat("(")
            args: list[object] = []
            if self.current.value != ")":
                args.append(self.parse_comparison())
                while self.current.value == ",":
                    self.eat(",")
                    args.append(self.parse_comparison())
            self.eat(")")
            return Call(name, tuple(args))

        if token.value == "(":
            self.eat("(")
            node = self.parse_comparison()
            self.eat(")")
            return node

        raise FormulaSyntaxError(f"意外的公式内容: {token.value!r}")


def parse_formula(text: str) -> object:
    """解析不带前导 = 的公式。"""
    if not text.strip():
        raise FormulaSyntaxError("公式不能为空")
    return Parser(text).parse()


def collect_references(node: object) -> tuple[set[tuple[int, int]], list[Range]]:
    cells: set[tuple[int, int]] = set()
    ranges: list[Range] = []

    def visit(value: object) -> None:
        if isinstance(value, Ref):
            cells.add((value.row, value.col))
        elif isinstance(value, RangeRef):
            ranges.append(value.cell_range)
            cells.update(value.cell_range.cells)
        elif isinstance(value, Unary):
            visit(value.operand)
        elif isinstance(value, Binary):
            visit(value.left)
            visit(value.right)
        elif isinstance(value, Call):
            for arg in value.args:
                visit(arg)

    visit(node)
    return cells, ranges
