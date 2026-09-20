from sheet.csv_io import save_csv
from sheet.display import render_range
from sheet.engine import SpreadsheetEngine
from sheet.model import CellAddress, Sheet
from sheet.repl import execute_command


def test_show_uses_fixed_aligned_format():
    engine = SpreadsheetEngine(Sheet())
    engine.set_cell(CellAddress(1, 1), "1")
    engine.set_cell(CellAddress(2, 1), "hello")
    engine.set_cell(CellAddress(1, 2), "12345")
    engine.set_cell(CellAddress(2, 2), "x")

    output = render_range(engine, CellAddress(1, 1), CellAddress(2, 2))
    assert output == (
        "  |     A |     B\n"
        "--+-------+------\n"
        "1 |     1 | hello\n"
        "2 | 12345 | x    "
    )


def test_truncates_wide_columns_with_ellipsis():
    engine = SpreadsheetEngine(Sheet())
    engine.set_cell(CellAddress(1, 1), "abcdefghijklmnopqrstuvwxyz")
    output = render_range(engine, CellAddress(1, 1), CellAddress(1, 1), max_width=8)
    assert "abcdefg…" in output


def test_repl_set_inspect_show_save_flow(tmp_path):
    data = tmp_path / "data.csv"
    data.write_text("100\n", encoding="utf-8")
    engine = SpreadsheetEngine(Sheet())

    _, message = execute_command(engine, f"load {data}")
    assert message.startswith("loaded")
    _, message = execute_command(engine, "set B2 =A1*1.08")
    assert message == "B2 = 108"
    _, message = execute_command(engine, "B2")
    assert message == "公式: =A1*1.08  值: 108"

    out = tmp_path / "out.csv"
    _, message = execute_command(engine, f"save {out}")
    assert message == f"saved {out}"

    # Loaded file had one column/row; editing B2 extends the exported grid.
    assert out.read_text(encoding="utf-8").splitlines() == [
        "100",
        ",108",
    ]


def test_set_accepts_spaceless_assignment():
    engine = SpreadsheetEngine(Sheet())
    _, message = execute_command(engine, "set A1 2")
    assert message == "A1 = 2"
    _, message = execute_command(engine, "set B2=A1+3")
    assert message == "B2 = 5"


def test_show_sanitizes_embedded_newlines():
    engine = SpreadsheetEngine(Sheet())
    engine.set_cell(CellAddress(1, 1), "line1\nline2")
    engine.set_cell(CellAddress(1, 2), "plain")

    output = render_range(engine, CellAddress(1, 1), CellAddress(1, 2))
    rows = output.splitlines()
    # The embedded newline must not split the table into extra ragged rows.
    assert len(rows) == 4  # header, separator, two data rows
    assert "line1⏎line2" in rows[2]
    assert rows[3].startswith("2 | plain")
