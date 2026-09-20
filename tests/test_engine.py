from sheet.engine import SpreadsheetEngine
from sheet.model import CellAddress, Sheet, display_value


def make_engine():
    return SpreadsheetEngine(Sheet())


def test_chain_dependency_recalculates_from_source():
    engine = make_engine()
    engine.set_cell(CellAddress(1, 1), "1")
    engine.set_cell(CellAddress(2, 1), "=A1+1")
    engine.set_cell(CellAddress(3, 1), "=B1+1")

    assert engine.value(CellAddress(2, 1)) == 2
    assert engine.value(CellAddress(3, 1)) == 3

    engine.set_cell(CellAddress(1, 1), "10")

    assert engine.value(CellAddress(2, 1)) == 11
    assert engine.value(CellAddress(3, 1)) == 12


def test_changing_cell_does_not_recalculate_unrelated_formula():
    engine = make_engine()
    engine.set_cell(CellAddress(1, 1), "2")
    engine.set_cell(CellAddress(2, 1), "=A1+10")
    unrelated_object = object()
    engine.values[CellAddress(4, 4)] = unrelated_object

    engine.set_cell(CellAddress(3, 3), "99")

    assert engine.values[CellAddress(4, 4)] is unrelated_object
    assert engine.value(CellAddress(2, 1)) == 12


def test_cycle_detection_reports_error_without_looping():
    engine = make_engine()
    engine.set_cell(CellAddress(1, 1), "=B1+1")
    engine.set_cell(CellAddress(2, 1), "=A1+1")

    assert display_value(engine.value(CellAddress(1, 1))) == "#CYCLE!"
    assert display_value(engine.value(CellAddress(2, 1))) == "#CYCLE!"


def test_breaking_cycle_restores_values():
    engine = make_engine()
    engine.set_cell(CellAddress(1, 1), "=B1+1")
    engine.set_cell(CellAddress(2, 1), "=A1+1")
    engine.set_cell(CellAddress(2, 1), "10")

    assert engine.value(CellAddress(1, 1)) == 11


def test_range_forms_and_blank_cells():
    engine = make_engine()
    for row, value in enumerate([1, 2, 3], 1):
        engine.set_cell(CellAddress(1, row), str(value))
    for col, value in enumerate([4, 5, 6], 1):
        engine.set_cell(CellAddress(col, 4), str(value))

    assert engine.value(CellAddress(4, 1)) is None
    engine.set_cell(CellAddress(4, 1), "=SUM(A1:A3)")
    engine.set_cell(CellAddress(4, 2), "=SUM(A4:C4)")
    engine.set_cell(CellAddress(4, 3), "=SUM(A1:C4)")
    engine.set_cell(CellAddress(4, 4), "=COUNT(A1:C4)")

    assert engine.value(CellAddress(4, 1)) == 6
    assert engine.value(CellAddress(4, 2)) == 15
    assert engine.value(CellAddress(4, 3)) == 21
    assert engine.value(CellAddress(4, 4)) == 6


def test_empty_scalar_reference_is_zero():
    engine = make_engine()
    engine.set_cell(CellAddress(2, 2), "=A1+5")
    assert engine.value(CellAddress(2, 2)) == 5
