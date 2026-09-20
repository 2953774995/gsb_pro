"""Interactive command-line interface for sheet."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from .csv_io import load_csv, save_csv
from .display import current_used_range, render_range
from .engine import FormulaError, SpreadsheetEngine
from .model import CellAddress, Sheet, display_value, parse_address

HELP = """\
commands:
  load <file.csv>   load a CSV file (replaces current sheet)
  save <file.csv>   save current computed values to CSV
  set <cell> <...>  set a number, text, or =formula (e.g. set B2 =A1*1.08)
  show [A1:D10]     show the whole sheet or a range
  clear <cell>      remove one cell
  help              show this help
  quit / exit       leave the program
"""


def parse_range(text: str) -> tuple[CellAddress, CellAddress]:
    text = text.strip().upper()
    if ":" in text:
        left, right = text.split(":", 1)
        start, end = parse_address(left), parse_address(right)
        return (
            CellAddress(min(start.col, end.col), min(start.row, end.row)),
            CellAddress(max(start.col, end.col), max(start.row, end.row)),
        )
    addr = parse_address(text)
    return addr, addr


def describe_cell(engine: SpreadsheetEngine, addr: CellAddress) -> str:
    content = engine.sheet.get_content(addr)
    value = engine.value(addr)
    if content.startswith("="):
        return f"公式: {content}  值: {display_value(value)}"
    if content:
        return f"文本: {content}  值: {display_value(value)}"
    return "空单元格  值: "


def execute_command(engine: SpreadsheetEngine, line: str) -> tuple[bool, str | None]:
    """Return ``(continue, output)``; output is ``None`` for silent command."""
    raw = line.strip()
    if not raw:
        return True, None

    parts = raw.split(None, 1)
    command = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""

    if command in ("quit", "exit"):
        return False, None
    if command == "help":
        return True, HELP.rstrip()

    if command == "load":
        if not argument:
            return True, "usage: load <file.csv>"
        try:
            sheet = load_csv(argument)
            engine.load_sheet(sheet)
        except (OSError, csv.Error) as exc:  # pragma: no cover - OS dependent
            return True, f"load failed: {exc}"
        used = current_used_range(engine.sheet)
        dims = (
            f"{used[1].col} columns x {used[1].row} rows"
            if used
            else "empty sheet"
        )
        return True, f"loaded {argument} ({dims})"

    if command == "save":
        if not argument:
            return True, "usage: save <file.csv>"
        try:
            save_csv(argument, engine.sheet, engine.values)
        except OSError as exc:  # pragma: no cover - OS dependent
            return True, f"save failed: {exc}"
        return True, f"saved {argument}"

    if command == "set":
        addr = None
        value_text = ""
        for index, ch in enumerate(argument):
            if ch != "=":
                continue
            cell_text = argument[:index].strip()
            try:
                addr = parse_address(cell_text)
            except ValueError:
                continue
            value_text = "=" + argument[index + 1:].strip()
            break

        if addr is None:
            parts = argument.split(None, 1)
            if len(parts) != 2:
                return True, "usage: set <cell> <number, text, or =formula>"
            try:
                addr = parse_address(parts[0])
            except ValueError:
                return True, "usage: set <cell> <number, text, or =formula>"
            value_text = parts[1].strip()
        err = engine.set_cell(addr, value_text.strip())
        if isinstance(err, FormulaError):
            return True, f"warning: invalid formula stored as #PARSE! ({err})"
        return True, f"{addr} = {display_value(engine.value(addr))}"

    if command == "clear":
        try:
            addr = parse_address(argument)
        except ValueError:
            return True, "usage: clear <cell>"
        engine.clear_cell(addr)
        return True, f"cleared {addr}"

    if command == "show":
        if argument:
            try:
                start, end = parse_range(argument)
            except ValueError as exc:
                return True, f"invalid range: {exc}"
        else:
            used = current_used_range(engine.sheet)
            if used is None:
                return True, "(empty sheet)"
            start, end = used
        return True, render_range(engine, start, end)

    # Bare cell address is an inspection shortcut.
    try:
        addr = parse_address(raw)
    except ValueError:
        return True, f"unknown command: {command} (try help)"
    return True, describe_cell(engine, addr)


def run_repl(engine: SpreadsheetEngine | None = None, *, infile=None, outfile=None) -> None:
    engine = engine or SpreadsheetEngine(Sheet())
    infile = infile or sys.stdin
    outfile = outfile or sys.stdout
    prompt = "sheet> " if infile.isatty() else ""

    if getattr(sys, "argv", None) and len(sys.argv) > 1:
        path = Path(sys.argv[1])
        if path.exists():
            _, output = execute_command(engine, f"load {path}")
            if output:
                print(output, file=outfile)

    while True:
        if prompt:
            print(prompt, end="", file=outfile, flush=True)
        line = infile.readline()
        if line == "":
            break
        keep_running, output = execute_command(engine, line)
        if output:
            print(output, file=outfile)
        if not keep_running:
            break
