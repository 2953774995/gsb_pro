"""CSV loading and saving on top of :class:`Sheet`."""

from __future__ import annotations

import csv
from pathlib import Path

from .model import CellAddress, Sheet, display_value


def load_csv(path: str | Path) -> Sheet:
    sheet = Sheet()
    with open(path, "r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    sheet.load_rows(rows)
    return sheet


def save_csv(path: str | Path, sheet: Sheet, values: dict[CellAddress, object] | None = None) -> None:
    values = values or {}
    width = sheet.export_width()
    row_count = sheet.export_row_count()
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for row in range(1, row_count + 1):
            explicit_width = sheet.widths.get(row, 0)
            # Keep explicitly empty rows distinct from an absent trailing row.
            if explicit_width == 0 and row in sheet.widths:
                writer.writerow([])
                continue
            row_width = explicit_width
            output = []
            for col in range(1, row_width + 1):
                addr = CellAddress(col, row)
                if addr in values:
                    output.append(display_value(values[addr]))
                else:
                    output.append(sheet.get_content(addr))
            writer.writerow(output)
