"""CSV 读写。导出公式时写计算后的显示值。"""

from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path

from .engine import Workbook, format_value, make_cell


def load_csv(path: str | Path, encoding: str = "utf-8-sig") -> Workbook:
    path = Path(path)
    with path.open("r", encoding=encoding, newline="") as stream:
        return parse_csv(stream.read())


def parse_csv(text: str) -> Workbook:
    reader = csv.reader(StringIO(text))
    wb = Workbook()
    for fields in reader:
        if not fields:
            # 真空行保留为空行；含分隔符的 ",," 行会保留为空字段。
            wb.rows.append([])
            continue
        wb.rows.append([make_cell(field) for field in fields])

    # 补齐成矩形，但不填充真空行。
    width = max((len(row) for row in wb.rows if row), default=0)
    for row in wb.rows:
        if row and len(row) < width:
            row.extend(make_cell("") for _ in range(width - len(row)))
    wb.recalculate_all()
    return wb


def save_csv(
    wb: Workbook, path: str | Path, encoding: str = "utf-8", lineterminator: str = "\n"
) -> None:
    path = Path(path)
    with path.open("w", encoding=encoding, newline="") as stream:
        write_csv(wb, stream, lineterminator=lineterminator)


def render_csv(wb: Workbook, lineterminator: str = "\n") -> str:
    stream = StringIO()
    write_csv(wb, stream, lineterminator=lineterminator)
    return stream.getvalue()


def write_csv(wb: Workbook, stream, lineterminator: str = "\n") -> None:
    writer = csv.writer(stream, lineterminator=lineterminator)
    for row in wb.rows:
        if not row:
            writer.writerow([])
        else:
            writer.writerow([format_value(cell.value) for cell in row])
