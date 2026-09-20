"""Terminal table rendering."""

from __future__ import annotations

import unicodedata

from .model import CellAddress, CellError, col_index_to_letter, display_value

DEFAULT_MAX_COLUMN_WIDTH = 20


def char_width(ch: str) -> int:
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def text_width(text: str) -> int:
    return sum(char_width(ch) for ch in text)


def pad_to_width(text: str, width: int, left: bool) -> str:
    diff = width - text_width(text)
    if diff <= 0:
        return text
    return text + " " * diff if left else " " * diff + text


def truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if text_width(text) <= width:
        return text
    if width == 1:
        return "…"
    out: list[str] = []
    used = 1  # ellipsis
    for ch in text:
        w = char_width(ch)
        if used + w > width:
            break
        out.append(ch)
        used += w
    return "".join(out) + "…"


def sanitize(text: str) -> str:
    """Make cell text safe for a single table row (no raw newlines/tabs)."""
    return (
        text.replace("\r\n", "\u23ce")
        .replace("\n", "\u23ce")
        .replace("\r", "\u23ce")
        .replace("\t", " ")
    )


def is_right_aligned(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) or isinstance(value, CellError)


def render_range(
    engine,
    start: CellAddress,
    end: CellAddress,
    *,
    max_width: int = DEFAULT_MAX_COLUMN_WIDTH,
) -> str:
    if start.col > end.col or start.row > end.row:
        return "(empty range)"

    header = [""] + [col_index_to_letter(c) for c in range(start.col, end.col + 1)]
    raw_rows: list[list[object]] = []
    for row in range(start.row, end.row + 1):
        values: list[object] = [row]
        for col in range(start.col, end.col + 1):
            addr = CellAddress(col, row)
            values.append(engine.value(addr))
        raw_rows.append(values)

    rendered_header = [str(x) for x in header]
    rendered_cells: list[list[str]] = []
    alignment_flags: list[list[bool]] = []
    for row_values in raw_rows:
        rendered = [str(row_values[0])]
        flags = [True]
        for value in row_values[1:]:
            rendered.append(sanitize(display_value(value)))
            flags.append(is_right_aligned(value))
        rendered_cells.append(rendered)
        alignment_flags.append(flags)

    col_count = len(header)
    widths: list[int] = []
    for c in range(col_count):
        content_widths = [text_width(rendered_header[c])]
        content_widths.extend(text_width(row[c]) for row in rendered_cells)
        widths.append(min(max(content_widths), max_width))

    def line(values: list[str], right: list[bool] | None = None) -> str:
        parts = []
        for i, value in enumerate(values):
            clipped = truncate(value, widths[i])
            parts.append(pad_to_width(clipped, widths[i], left=not (right and right[i])))
        return " | ".join(parts)

    lines = [line(rendered_header, [False] + [True] * (len(header) - 1)), "-+-".join("-" * width for width in widths)]
    for row, flags in zip(rendered_cells, alignment_flags):
        lines.append(line(row, flags))
    return "\n".join(lines)


def current_used_range(sheet) -> tuple[CellAddress, CellAddress] | None:
    if sheet.max_row <= 0 or sheet.max_col <= 0:
        return None
    return CellAddress(1, 1), CellAddress(sheet.max_col, sheet.max_row)
