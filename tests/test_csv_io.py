import csv

from sheet.csv_io import load_csv, save_csv
from sheet.engine import SpreadsheetEngine
from sheet.model import CellAddress


def test_csv_quotes_commas_newlines_and_blank_rows(tmp_path):
    source = tmp_path / "data.csv"
    source.write_text(
        'name,note\n"Smith, Jane","line1\nline2"\n\n,,\n',
        encoding="utf-8",
    )

    sheet = load_csv(source)
    assert sheet.get_content(CellAddress(1, 2)) == "Smith, Jane"
    assert sheet.get_content(CellAddress(2, 2)) == "line1\nline2"
    assert sheet.widths[3] == 0
    assert sheet.widths[4] == 3

    out = tmp_path / "out.csv"
    engine = SpreadsheetEngine(sheet)
    save_csv(out, sheet, engine.values)

    rows = list(csv.reader(out.open(newline="", encoding="utf-8")))
    assert rows == [
        ["name", "note"],
        ["Smith, Jane", "line1\nline2"],
        [],
        ["", "", ""],
    ]


def test_saved_csv_writes_formula_results(tmp_path):
    source = tmp_path / "data.csv"
    source.write_text("100\n", encoding="utf-8")
    sheet = load_csv(source)
    engine = SpreadsheetEngine(sheet)
    engine.set_cell(CellAddress(2, 1), "=A1*1.08")
    engine.set_cell(CellAddress(3, 1), '="total"')

    out = tmp_path / "out.csv"
    save_csv(out, sheet, engine.values)
    rows = list(csv.reader(out.open(newline="", encoding="utf-8")))
    assert rows == [["100", "108", "total"]]
