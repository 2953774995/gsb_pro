"""工作簿数据模型、公式求值、依赖图和增量重算。"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Optional

from .address import Range, join_address, split_address
from .formula import (
    Binary,
    Boolean,
    Call,
    FormulaSyntaxError,
    Number,
    RangeRef,
    Ref,
    Text,
    Unary,
    collect_references,
    parse_formula,
)


class CellError(Exception):
    """单元格错误值。"""

    display = "#ERROR!"

    def __str__(self) -> str:
        return self.display


class DivisionByZeroError(CellError):
    display = "#DIV/0!"


class ValueError_(CellError):
    display = "#VALUE!"


class NameError_(CellError):
    display = "#NAME?"


class ReferenceError_(CellError):
    display = "#REF!"


class CycleError(CellError):
    display = "#CYCLE!"


ERROR_BY_NAME = {
    "DIV0": DivisionByZeroError(),
    "VALUE": ValueError_(),
    "NAME": NameError_(),
    "REF": ReferenceError_(),
    "CYCLE": CycleError(),
}


@dataclass
class Cell:
    raw: str = ""
    is_formula: bool = False
    ast: object = None
    value: object = ""
    syntax_error: str | None = None


_INT_RE = re.compile(r"[+-]?\d+$")
_FLOAT_RE = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?$")


def parse_literal(text: str) -> object:
    stripped = text.strip()
    if stripped == "":
        return ""
    lower = stripped.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    # 仅把普通十进制数字转成数字；inf/nan 保留为文本，避免污染统计。
    if _INT_RE.fullmatch(stripped):
        try:
            return int(stripped)
        except ValueError:
            return text
    if _FLOAT_RE.fullmatch(stripped):
        try:
            number = float(stripped)
        except ValueError:
            return text
        return number if math.isfinite(number) else text
    return text


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def to_number(value: object) -> float | int:
    if isinstance(value, CellError):
        raise value
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return 1 if value else 0
    if is_number(value):
        return value
    if isinstance(value, str):
        parsed = parse_literal(value)
        if is_number(parsed):
            return parsed
    raise ValueError_()


def format_number(value: int | float) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if value == 0:
        number = 0.0
    else:
        number = float(f"{value:.10g}")
    if float(number).is_integer() and abs(number) < 1e16:
        return f"{number:.1f}"
    return ("%.10g" % number)


def to_text(value: object) -> str:
    if isinstance(value, CellError):
        raise value
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if is_number(value):
        return format_number(value)
    return str(value)


def format_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, CellError):
        return str(value)
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if is_number(value):
        return format_number(value)
    return str(value)


def make_cell(raw: str) -> Cell:
    raw = "" if raw is None else str(raw)
    cell = Cell(raw=raw)
    if raw.startswith("="):
        cell.is_formula = True
        try:
            cell.ast = parse_formula(raw[1:])
        except FormulaSyntaxError as exc:
            cell.syntax_error = str(exc)
            cell.value = ValueError_()
    else:
        cell.value = parse_literal(raw)
    return cell


class Workbook:
    def __init__(self) -> None:
        self.rows: list[list[Cell]] = []
        # dependencies[cell] = 该公式直接引用的格子。
        self.dependencies: dict[tuple[int, int], set[tuple[int, int]]] = {}
        # dependents[source] = 直接依赖 source 的公式。
        self.dependents: dict[tuple[int, int], set[tuple[int, int]]] = {}

    @property
    def max_row(self) -> int:
        return len(self.rows)

    @property
    def max_col(self) -> int:
        return max((len(row) for row in self.rows), default=0)

    def _ensure(self, row: int, col: int) -> None:
        while len(self.rows) <= row:
            self.rows.append([])
        while len(self.rows[row]) <= col:
            self.rows[row].append(Cell())

    def get_cell(self, row: int, col: int) -> Cell:
        if 0 <= row < len(self.rows) and 0 <= col < len(self.rows[row]):
            return self.rows[row][col]
        return Cell()

    def get_value(self, row: int, col: int) -> object:
        return self.get_cell(row, col).value

    def set_value(self, row: int, col: int, raw: str) -> None:
        key = (row, col)
        old_deps = self.dependencies.pop(key, set())
        for source in old_deps:
            self.dependents.get(source, set()).discard(key)

        had_cell = row < len(self.rows) and col < len(self.rows[row])
        old_raw = self.get_cell(row, col).raw if had_cell else ""
        cell = make_cell(raw)

        if raw == "" and not had_cell and row >= self.max_row and col >= self.max_col:
            # 不把表格边界外的空白输入物化成格子。
            return
        self._ensure(row, col)
        self.rows[row][col] = cell
        self._trim()

        affected: set[tuple[int, int]] = {key}
        if cell.is_formula and cell.ast is not None:
            refs, _ranges = collect_references(cell.ast)
            self.dependencies[key] = set(refs)
            for source in refs:
                self.dependents.setdefault(source, set()).add(key)
        else:
            # 常量/空单元格没有公式出边。
            pass

        self._collect_dependents(key, affected)
        # 删除原有非空格子内容也必须通知依赖者。
        if old_raw != raw or not raw:
            pass
        self._recalculate(affected)

    def _collect_dependents(
        self, start: tuple[int, int], result: set[tuple[int, int]]
    ) -> None:
        stack = [start]
        while stack:
            key = stack.pop()
            for dependent in self.dependents.get(key, ()):
                if dependent not in result:
                    result.add(dependent)
                    stack.append(dependent)

    def _recalculate(self, affected: set[tuple[int, int]]) -> None:
        # 在受影响子图上做 Kahn 拓扑排序；最后未结算的公式即处于环中，
        # 其下游也继续保持 #CYCLE!。
        indegree: dict[tuple[int, int], int] = {}
        for key in affected:
            row, col = key
            cell = self.get_cell(row, col)
            if cell.is_formula:
                # 语法错误的公式没有依赖边，必须立即求值并保留 #VALUE!。
                indegree[key] = len(self.dependencies.get(key, set()) & affected)

        # 受影响的非公式格子是依赖边的起点，要作为 Kahn 队列的种子。
        ready = [key for key in affected if key not in indegree]
        ready.extend(key for key, degree in indegree.items() if degree == 0)
        processed: set[tuple[int, int]] = set()

        while ready:
            key = ready.pop()
            if key in processed:
                continue
            row, col = key
            cell = self.get_cell(row, col)
            if cell.is_formula:
                if cell.syntax_error is not None:
                    cell.value = ValueError_()
                else:
                    try:
                        cell.value = Evaluator(self).evaluate(cell.ast)
                    except CellError as exc:
                        cell.value = exc
            processed.add(key)
            for dependent in self.dependents.get(key, ()):
                if dependent in indegree:
                    indegree[dependent] -= 1
                    if indegree[dependent] == 0:
                        ready.append(dependent)

        for key in affected - processed:
            row, col = key
            cell = self.get_cell(row, col)
            if cell.is_formula:
                cell.value = CycleError()

    def _trim(self) -> None:
        while self.rows and not any(cell.raw for cell in self.rows[-1]):
            self.rows.pop()
        max_len = 0
        for row in self.rows:
            last = 0
            for index, cell in enumerate(row):
                if cell.raw:
                    last = index + 1
            del row[last:]
            if len(row) > max_len:
                max_len = len(row)
        for row in self.rows:
            # [] 表示 CSV 中的真空行，不把它补成空字段行。
            if row and len(row) < max_len:
                row.extend(Cell() for _ in range(max_len - len(row)))

    def recalculate_all(self) -> None:
        self.dependencies.clear()
        self.dependents.clear()
        formulas: set[tuple[int, int]] = set()
        for r, row in enumerate(self.rows):
            for c, cell in enumerate(row):
                if cell.is_formula and cell.ast is not None:
                    key = (r, c)
                    refs, _ = collect_references(cell.ast)
                    self.dependencies[key] = refs
                    for source in refs:
                        self.dependents.setdefault(source, set()).add(key)
                    formulas.add(key)
        self._recalculate(set(formulas))

    def address_value(self, address: str) -> object:
        row, col = split_address(address)
        return self.get_value(row, col)


class Evaluator:
    def __init__(self, workbook: Workbook):
        self.wb = workbook

    def evaluate(self, node: object) -> object:
        if isinstance(node, Number):
            return node.value
        if isinstance(node, Text):
            return node.value
        if isinstance(node, Boolean):
            return node.value
        if isinstance(node, Ref):
            return self.wb.get_value(node.row, node.col)
        if isinstance(node, RangeRef):
            # 区域只能作为函数参数；单独写 =A1:A3 没有明确语义。
            raise ValueError_()
        if isinstance(node, Unary):
            value = to_number(self.evaluate(node.operand))
            return value if node.op == "+" else -value
        if isinstance(node, Binary):
            return self.binary(node)
        if isinstance(node, Call):
            return self.call(node)
        raise ValueError_()

    def binary(self, node: Binary) -> object:
        op = node.op
        if op == "&":
            return to_text(self.evaluate(node.left)) + to_text(
                self.evaluate(node.right)
            )
        if op in ("=", "<>", "<", "<=", ">", ">="):
            return self.compare(op, node.left, node.right)

        left = to_number(self.evaluate(node.left))
        right = to_number(self.evaluate(node.right))
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            if right == 0:
                raise DivisionByZeroError()
            result = left / right
            # 整除风格：两边均为整数且能整除时保留 int，展示仍为 108.0 时不影响。
            if isinstance(left, int) and isinstance(right, int) and left % right == 0:
                return int(result)
            return result
        raise ValueError_()

    def compare(self, op: str, left_node: object, right_node: object) -> bool:
        left = self.evaluate(left_node)
        right = self.evaluate(right_node)
        if isinstance(left, CellError):
            raise left
        if isinstance(right, CellError):
            raise right

        # 空既按 0 也可与空文本比较；这让 CSV 空单元格符合“引用空按 0”。
        if left == "" and right == "":
            lx: object = 0
            rx: object = 0
        elif left == "" and is_number(right):
            lx, rx = 0, right
        elif right == "" and is_number(left):
            lx, rx = left, 0
        elif isinstance(left, bool) or isinstance(right, bool):
            lx, rx = left, right
        elif is_number(left) and is_number(right):
            lx, rx = left, right
        elif isinstance(left, str) and isinstance(right, str):
            lx, rx = left, right
        else:
            raise ValueError_()

        if op == "=":
            return lx == rx
        if op == "<>":
            return lx != rx
        if op == "<":
            return lx < rx
        if op == "<=":
            return lx <= rx
        if op == ">":
            return lx > rx
        if op == ">=":
            return lx >= rx
        raise ValueError_()

    def call(self, node: Call) -> object:
        name = node.name.upper()
        expanded: list[tuple[str, object]] = []
        for arg in node.args:
            if isinstance(arg, RangeRef):
                for row, col in arg.cell_range.cells:
                    value = self.wb.get_value(row, col)
                    if isinstance(value, CellError):
                        raise value
                    if value == "":
                        continue
                    expanded.append(("range", value))
                continue
            value = self.evaluate(arg)
            if isinstance(value, CellError):
                raise value
            expanded.append(("scalar", value))

        if name == "COUNT":
            return sum(1 for kind, value in expanded if is_number(value))

        numbers: list[int | float] = []
        for kind, value in expanded:
            if is_number(value):
                numbers.append(value)
            elif kind == "scalar":
                raise ValueError_()
            # 区域里的文本和布尔值与常见电子表格一样，被数值聚合忽略。

        if name in ("AVG", "AVERAGE"):
            if not numbers:
                raise DivisionByZeroError()
            return sum(numbers) / len(numbers)
        if name == "SUM":
            return sum(numbers)
        if name == "MIN":
            return min(numbers) if numbers else 0
        if name == "MAX":
            return max(numbers) if numbers else 0
        raise NameError_()
