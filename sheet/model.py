"""Spreadsheet address, storage and display-value helpers."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

ADDRESS_RE = re.compile(r"^([A-Za-z]+)([1-9][0-9]*)$")
NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")

# Error values are kept as distinct subclasses so formulas can propagate an
# error without confusing it with ordinary text.
class CellError:
    token = "#ERROR!"

    def __init__(self, message: str | None = None) -> None:
        self.message = message

    def __str__(self) -> str:
        return self.token

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.message!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CellError) and self.token == other.token


class DivByZeroError(CellError):
    token = "#DIV/0!"


class CycleErrorValue(CellError):
    token = "#CYCLE!"


class ParseErrorValue(CellError):
    token = "#PARSE!"


class TypeErrorValue(CellError):
    token = "#VALUE!"


@dataclass(frozen=True)
class CellAddress:
    col: int  # one-based
    row: int  # one-based

    def __str__(self) -> str:
        return f"{col_index_to_letter(self.col)}{self.row}"


def col_letter_to_index(letters: str) -> int:
    """Convert A..Z, AA.. to a one-based column number."""
    letters = letters.upper()
    if not letters or not letters.isalpha():
        raise ValueError(f"invalid column letters: {letters!r}")
    value = 0
    for ch in letters:
        value = value * 26 + (ord(ch) - ord("A") + 1)
    return value


def col_index_to_letter(index: int) -> str:
    if index < 1:
        raise ValueError("column index must be positive")
    chars: list[str] = []
    while index:
        index, rem = divmod(index - 1, 26)
        chars.append(chr(ord("A") + rem))
    return "".join(reversed(chars))


def parse_address(text: str) -> CellAddress:
    match = ADDRESS_RE.match(text.strip().upper())
    if not match:
        raise ValueError(f"invalid cell address: {text!r}")
    return CellAddress(col_letter_to_index(match.group(1)), int(match.group(2)))


def parse_number(text: str) -> float | None:
    text = text.strip()
    if NUMBER_RE.fullmatch(text):
        return float(text)
    return None


def format_number(value: float) -> str:
    if math.isnan(value) or math.isinf(value):
        return "#VALUE!"
    if value == int(value) and abs(value) < 1e16:
        return str(int(value))
    return repr(value)


def display_value(value: object) -> str:
    """Render an evaluated value for direct inspection, show and CSV export."""
    if value is None:
        return ""
    if isinstance(value, CellError):
        return value.token
    if value is True:
        return "TRUE"
    if value is False:
        return "FALSE"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return format_number(float(value))
    return str(value)


class Sheet:
    """Rectangular CSV-backed sheet.

    ``cells`` stores the user-entered content. A string beginning with ``=`` is
    a formula. ``widths`` preserves CSV row width so trailing empty fields and
    genuinely empty rows survive a load/save round trip.
    """

    def __init__(self) -> None:
        self.cells: dict[CellAddress, str] = {}
        self.widths: dict[int, int] = {}  # row -> explicit field count
        self.max_col = 0
        self.max_row = 0

    def _bump_dimensions(self, col: int, row: int) -> None:
        self.max_col = max(self.max_col, col)
        self.max_row = max(self.max_row, row)

    def set_raw(self, col: int, row: int, content: str) -> CellAddress:
        addr = CellAddress(col, row)
        content = "" if content is None else str(content)
        if content:
            self.cells[addr] = content
            self._bump_dimensions(col, row)
            self.widths[row] = max(self.widths.get(row, 0), col)
        else:
            # Setting a cell blank can still establish a trailing field's width.
            self.cells.pop(addr, None)
            self.widths[row] = max(self.widths.get(row, 0), col)
            self._bump_dimensions(col, row)
        return addr

    def set_content(self, addr: CellAddress, content: str | None) -> None:
        self.set_raw(addr.col, addr.row, content or "")

    def get_content(self, addr: CellAddress) -> str:
        return self.cells.get(addr, "")

    def clear(self, addr: CellAddress) -> None:
        self.cells.pop(addr, None)
        self._refresh_dimensions()

    def clear_sheet(self) -> None:
        self.cells.clear()
        self.widths.clear()
        self.max_col = self.max_row = 0

    def load_rows(self, rows: list[list[str]]) -> None:
        self.clear_sheet()
        for r, row in enumerate(rows, 1):
            # csv.reader returns [] for a blank line; [""] for a delimited blank.
            if row:
                self.widths[r] = len(row)
            else:
                self.widths[r] = 0
            for c, value in enumerate(row, 1):
                if value:
                    addr = CellAddress(c, r)
                    self.cells[addr] = value
                    self.max_col = max(self.max_col, c)
            self.max_row = max(self.max_row, r)

    def _refresh_dimensions(self) -> None:
        max_col = 0
        max_row = 0
        width_rows = set(self.widths)
        for addr in self.cells:
            max_col = max(max_col, addr.col)
            max_row = max(max_row, addr.row)
        for row, width in self.widths.items():
            width_rows.add(row)
            if width > 0:
                max_col = max(max_col, width)
                max_row = max(max_row, row)
        self.max_col = max_col
        self.max_row = max_row
        # Explicit widths after the last meaningful row are still meaningful.
        self.widths = {r: w for r, w in self.widths.items() if r <= max_row}

    def export_width(self) -> int:
        return max([self.max_col, 1] + list(self.widths.values()))

    def export_row_count(self) -> int:
        return self.max_row

    def row_width(self, row: int) -> int:
        return max(self.max_col, self.widths.get(row, 0))
