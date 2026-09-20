"""A1 样式的列名/单元格地址/区域工具。"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CELL_RE = re.compile(r"^([A-Za-z]+)([0-9]+)$")


def col_to_index(col: str) -> int:
    """把 A、B、...、AA 转成 0 起始列下标。"""
    if not col or not col.isalpha() or not col.isascii():
        raise ValueError(f"无效列名: {col!r}")
    value = 0
    for char in col.upper():
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value - 1


def index_to_col(index: int) -> str:
    """把 0 起始列下标转回 A、B、...、AA。"""
    if index < 0:
        raise ValueError("列下标不能为负数")
    result = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        result = chr(ord("A") + rem) + result
    return result


def split_address(address: str) -> tuple[int, int]:
    """解析 A1，返回 (row_index, col_index)，均为 0 起始。"""
    match = _CELL_RE.fullmatch(address.strip().upper())
    if not match:
        raise ValueError(f"无效单元格地址: {address!r}")
    col_text, row_text = match.groups()
    row = int(row_text) - 1
    if row < 0:
        raise ValueError(f"无效行号: {address!r}")
    return row, col_to_index(col_text)


def join_address(row: int, col: int) -> str:
    if row < 0 or col < 0:
        raise ValueError("行列下标不能为负数")
    return f"{index_to_col(col)}{row + 1}"


@dataclass(frozen=True)
class Range:
    """0 起始、两端都包含的矩形区域。"""

    start_row: int
    start_col: int
    end_row: int
    end_col: int

    @classmethod
    def parse(cls, text: str) -> "Range":
        parts = text.strip().split(":")
        if len(parts) != 2:
            raise ValueError(f"无效区域: {text!r}")
        sr, sc = split_address(parts[0])
        er, ec = split_address(parts[1])
        if er < sr or ec < sc:
            raise ValueError(f"区域起点不能大于终点: {text!r}")
        return cls(sr, sc, er, ec)

    @classmethod
    def cell(cls, row: int, col: int) -> "Range":
        return cls(row, col, row, col)

    @property
    def cells(self) -> list[tuple[int, int]]:
        return [
            (r, c)
            for r in range(self.start_row, self.end_row + 1)
            for c in range(self.start_col, self.end_col + 1)
        ]

    def __str__(self) -> str:
        return (
            f"{join_address(self.start_row, self.start_col)}:"
            f"{join_address(self.end_row, self.end_col)}"
        )


def parse_cell_or_range(text: str) -> str:
    """供 REPL/show 使用：规范化单元格或区域字符串。"""
    value = text.strip().upper()
    if ":" in value:
        return str(Range.parse(value))
    split_address(value)
    return value
