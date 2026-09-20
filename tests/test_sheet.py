import io
from pathlib import Path

import pytest

from sheet.address import Range, col_to_index, index_to_col, split_address
from sheet.csv_io import parse_csv, render_csv
from sheet.display import render_table
from sheet.engine import Workbook, format_value
from sheet.formula import parse_formula
from sheet.repl import Repl


def wb_from_rows(rows):
    wb = Workbook()
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            wb.set_value(r, c, value)
    return wb


def cell(wb, address):
    r, c = split_address(address)
    return wb.get_cell(r, c)


def val(wb, address):
    r, c = split_address(address)
    return wb.get_value(r, c)


def test_column_address_helpers():
    assert col_to_index("A") == 0
    assert col_to_index("Z") == 25
    assert col_to_index("AA") == 26
    assert col_to_index("AB") == 27
    assert index_to_col(26) == "AA"
    assert split_address("BC12") == (11, 54)


def test_formula_precedence_parentheses_and_negative_numbers():
    wb = Workbook()
    wb.set_value(0, 0, "10")
    wb.set_value(1, 0, "=2+3*4")
    wb.set_value(2, 0, "=(2+3)*4")
    wb.set_value(3, 0, "=-A1*2")
    wb.set_value(4, 0, "=--5")
    wb.set_value(5, 0, "=8/2/2")
    assert val(wb, "A2") == 14
    assert val(wb, "A3") == 20
    assert val(wb, "A4") == -20
    assert val(wb, "A5") == 5
    assert val(wb, "A6") == 2


def test_nested_range_functions_and_missing_cell_is_zero():
    wb = wb_from_rows(
        [
            ["1", "5"],
            ["2", ""],
            ["", "7"],
            ["4", "9"],
            ["5", "11"],
        ]
    )
    wb.set_value(0, 2, "=SUM(A1:A5)+MAX(B1:B5)")
    wb.set_value(1, 2, "=AVG(A1:A5)")
    wb.set_value(2, 2, "=COUNT(B1:B5)")
    wb.set_value(3, 2, "=MIN(B1:B5)")
    assert val(wb, "C1") == 23
    assert val(wb, "C2") == 3
    assert val(wb, "C3") == 4
    assert val(wb, "C4") == 5
    # 空单元格参与算术时按 0。
    wb.set_value(4, 2, "=B2+1")
    assert val(wb, "C5") == 1


def test_single_row_single_column_and_cross_shaped_ranges():
    wb = wb_from_rows([["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"]])
    wb.set_value(0, 3, "=SUM(A1:C1)")
    wb.set_value(1, 3, "=SUM(A1:A3)")
    wb.set_value(2, 3, "=SUM(A1:C3)")
    assert val(wb, "D1") == 6
    assert val(wb, "D2") == 12
    assert val(wb, "D3") == 45
    assert str(Range.parse("B2:D4")) == "B2:D4"


def test_comparison_and_string_concatenation():
    wb = Workbook()
    wb.set_value(0, 0, "120")
    wb.set_value(0, 1, "=A1>100")
    wb.set_value(1, 0, "80")
    wb.set_value(1, 1, "=A2>=100")
    wb.set_value(2, 1, '="合计: "&A1')
    assert val(wb, "B1") is True
    assert val(wb, "B2") is False
    assert val(wb, "B3") == "合计: 120"
    assert format_value(val(wb, "B1")) == "TRUE"


def test_division_by_zero_and_error_display():
    wb = Workbook()
    wb.set_value(0, 0, "1")
    wb.set_value(0, 1, "=A1/0")
    wb.set_value(0, 2, "=AVG(B1:B3)")
    wb.set_value(0, 3, "=B1+1")
    assert format_value(val(wb, "B1")) == "#DIV/0!"
    assert format_value(val(wb, "C1")) == "#DIV/0!"
    assert format_value(val(wb, "D1")) == "#DIV/0!"


def test_invalid_formula_is_value_error():
    wb = Workbook()
    wb.set_value(0, 0, "=1+")
    assert format_value(val(wb, "A1")) == "#VALUE!"


def test_chain_dependencies_recalculate_in_order():
    wb = Workbook()
    wb.set_value(0, 0, "1")
    wb.set_value(0, 1, "=A1+1")
    wb.set_value(0, 2, "=B1*10")
    assert val(wb, "B1") == 2
    assert val(wb, "C1") == 20

    wb.set_value(0, 0, "5")
    assert val(wb, "B1") == 6
    assert val(wb, "C1") == 60


def test_changing_cell_does_not_affect_unrelated_formula():
    wb = Workbook()
    wb.set_value(0, 0, "1")
    wb.set_value(0, 1, "=A1+1")
    wb.set_value(0, 4, "10")
    wb.set_value(0, 5, "=E1+1")

    calls = []
    original = type(wb)._recalculate

    def spy(workbook, affected):
        calls.append(set(affected))
        return original(workbook, affected)

    type(wb)._recalculate = spy
    try:
        wb.set_value(0, 0, "2")
    finally:
        type(wb)._recalculate = original

    assert val(wb, "B1") == 3
    assert val(wb, "F1") == 11
    assert (0, 5) not in calls[0]


def test_cycle_is_reported_not_infinite_loop():
    wb = Workbook()
    wb.set_value(0, 0, "=B1+1")
    wb.set_value(0, 1, "=A1+1")
    wb.set_value(0, 2, "=B1*2")
    assert format_value(val(wb, "A1")) == "#CYCLE!"
    assert format_value(val(wb, "B1")) == "#CYCLE!"
    assert format_value(val(wb, "C1")) == "#CYCLE!"

    wb.set_value(0, 1, "10")
    assert val(wb, "A1") == 11
    assert val(wb, "B1") == 10
    assert val(wb, "C1") == 20


def test_self_reference_is_cycle():
    wb = Workbook()
    wb.set_value(0, 0, "=A1+1")
    assert format_value(val(wb, "A1")) == "#CYCLE!"


def test_dependency_graph_uses_direct_edges():
    wb = Workbook()
    wb.set_value(0, 0, "1")
    wb.set_value(0, 1, "=A1+SUM(A1:A2)")
    wb.set_value(1, 0, "2")
    assert wb.dependencies[(0, 1)] == {(0, 0), (1, 0)}
    assert wb.dependents[(0, 0)] == {(0, 1)}


def test_csv_quoted_comma_newline_blank_rows_and_save_values(tmp_path):
    content = (
        'name,note,amount\n'
        '"Doe, Alice","line1\nline2",10\n'
        '\n'
        ',,\n'
        'Bob,"say ""hi""",20\n'
    )
    path = tmp_path / "data.csv"
    path.write_text(content, encoding="utf-8")

    wb = parse_csv(content)
    assert wb.rows[1][0].raw == "Doe, Alice"
    assert wb.rows[1][1].raw == "line1\nline2"
    assert wb.rows[2] == []  # 真空行
    assert [c.raw for c in wb.rows[3]] == ["", "", ""]
    assert wb.rows[4][1].raw == 'say "hi"'

    wb.set_value(0, 3, "=SUM(C2:C5)")
    assert val(wb, "D1") == 30
    output = render_csv(wb)
    assert "Doe, Alice" in output
    assert '"line1\nline2"' in output
    assert "30" in output.splitlines()[0]
    assert "=SUM" not in output


def test_show_formats_and_truncates_fixed_data():
    wb = wb_from_rows(
        [
            ["name", "amount"],
            ["apple", "10"],
            ["非常长的水果名字用于测试截断效果", "200"],
        ]
    )
    output = render_table(wb)
    assert output == (
        "    A                   | B\n"
        " 1  name                | amount\n"
        " 2  apple               |     10\n"
        " 3  非常长的水果名字用… |    200"
    )


def test_show_partial_range():
    wb = wb_from_rows([["1", "2", "3"], ["4", "5", "6"]])
    output = render_table(wb, Range.parse("B1:C2"))
    lines = output.splitlines()
    assert lines[0].endswith("B   | C")
    assert lines[1].endswith("2 |   3")
    assert lines[2].endswith("5 |   6")


def test_repl_set_inspect_show_and_save(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("price\n100\n", encoding="utf-8")
    out = io.StringIO()
    repl = Repl(out=out)

    assert repl.execute(f"load {source}") == "已加载 {0}：2 行，1 列".format(source)
    assert repl.execute("set B1 =A2*1.08").endswith("->  108.0")
    assert repl.execute("B1") == "公式: =A2*1.08  值: 108.0"
    shown = repl.execute("show A1:B2")
    assert "price" in shown and "108.0" in shown

    target = tmp_path / "out.csv"
    assert repl.execute(f"save {target}").startswith("已保存")
    saved = target.read_text(encoding="utf-8")
    assert "price,108.0\n" in saved


def test_repl_reports_cycle_and_help():
    out = io.StringIO()
    repl = Repl(out=out)
    repl.execute("set A1 =B1+1")
    repl.execute("set B1 =A1+1")
    assert repl.execute("A1") == "公式: =B1+1  值: #CYCLE!"
    assert "SUM(A1:A10)" in repl.execute("help")


def test_repl_set_constant_text_and_clear():
    out = io.StringIO()
    repl = Repl(out=out)

    # 数字常量
    assert repl.execute("set A1 123") == "A1 = 123  ->  123"
    assert repl.execute("A1") == "地址: A1  值: 123"
    # 文本常量
    assert repl.execute("set A2 hello") == "A2 = hello  ->  hello"
    assert repl.execute("A2") == "地址: A2  值: hello"
    # 公式仍然以 = 开头
    assert repl.execute("set B1 =A1*2") == "B1 = =A1*2  ->  246"
    # 清空单元格后，依赖它的公式按空（0）重算
    assert repl.execute("set A1") == "A1 已清空"
    assert repl.execute("B1") == "公式: =A1*2  值: 0"
