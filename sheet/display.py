"""show 命令的表格格式化。"""

from __future__ import annotations

import unicodedata

from .address import Range, index_to_col
from .engine import CellError, Workbook, format_value, is_number

MAX_WIDTH = 20


def char_width(char: str) -> int:
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def display_width(text: str) -> int:
    return sum(char_width(char) for char in text)


def pad(text: str, width: int, align: str = "left") -> str:
    gap = max(0, width - display_width(text))
    if align == "right":
        return " " * gap + text
    return text + " " * gap


def truncate(text: str, width: int) -> str:
    if display_width(text) <= width:
        return text
    # 列宽小于 3 时仍至少给省略号，正常列保留一个字符 + "…"。
    if width <= 1:
        return "…"[:width]
    result = ""
    used = 1  # 省略号自身宽度
    for char in text:
        char_w = char_width(char)
        if used + char_w > width:
            break
        result += char
        used += char_w
    return result + "…"


def render_table(
    wb: Workbook,
    cell_range: Range | None = None,
    max_width: int = MAX_WIDTH,
) -> str:
    if wb.max_row == 0 or wb.max_col == 0:
        return "(空表)"

    if cell_range is None:
        start_row = start_col = 0
        end_row, end_col = wb.max_row - 1, wb.max_col - 1
    else:
        start_row, start_col = cell_range.start_row, cell_range.start_col
        end_row, end_col = cell_range.end_row, cell_range.end_col

    row_count = end_row - start_row + 1
    col_count = end_col - start_col + 1
    headers = [
        index_to_col(start_col + index) for index in range(col_count)
    ]
    widths = [max(3, min(max_width, display_width(header))) for header in headers]

    rendered: list[list[tuple[str, str]]] = []
    for r in range(start_row, end_row + 1):
        line: list[tuple[str, str]] = []
        for offset, c in enumerate(range(start_col, end_col + 1)):
            if r < len(wb.rows) and c < len(wb.rows[r]):
                value = wb.rows[r][c].value
            else:
                value = ""
            text = format_value(value)
            text = truncate(text, max_width)
            align = "right" if is_number(value) and not isinstance(value, CellError) else "left"
            line.append((text, align))
            widths[offset] = max(widths[offset], min(display_width(text), max_width))
        rendered.append(line)

    row_label_width = max(2, len(str(end_row + 1)))
    lines: list[str] = []
    header = " " * row_label_width + "  " + " | ".join(
        pad(header, widths[i], "left") for i, header in enumerate(headers)
    )
    lines.append(header.rstrip())

    for index, line in enumerate(rendered):
        row_number = start_row + index + 1
        cells = " | ".join(
            pad(text, widths[i], align) for i, (text, align) in enumerate(line)
        )
        lines.append(f"{pad(str(row_number), row_label_width, 'right')}  {cells}".rstrip())

    return "\n".join(lines)
