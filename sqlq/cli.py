"""Command line interface for sqlq.

Usage:
    python3 -m sqlq                  # interactive REPL
    python3 -m sqlq file.sql ...     # execute files and exit
    echo "SELECT 1;" | python3 -m sqlq -   # read SQL from stdin
"""

import argparse
import sys

from .engine import Engine
from .errors import SqlqError
from .values import sql_repr


def render_table(columns, rows):
    """Render a result set as an aligned ASCII table."""
    header = [str(name) for name in columns]
    body = [[sql_repr(value) for value in row] for row in rows]
    widths = [len(name) for name in header]
    for row in body:
        for i, cell in enumerate(row):
            if len(cell) > widths[i]:
                widths[i] = len(cell)

    def border(left, mid, right, fill="-"):
        return left + mid.join(fill * (width + 2) for width in widths) + right

    def format_row(cells):
        return "| " + " | ".join(
            cell.ljust(widths[i]) for i, cell in enumerate(cells)
        ) + " |"

    lines = [
        border("+", "+", "+"),
        format_row(header),
        border("+", "+", "+"),
    ]
    for row in body:
        lines.append(format_row(row))
    lines.append(border("+", "+", "+"))
    return "\n".join(lines)


def execute_and_render(engine, sql, out):
    result = engine.execute(sql)
    if result.statement_type == "SELECT":
        print(render_table(result.columns, result.rows), file=out)
        noun = "row" if len(result.rows) == 1 else "rows"
        print(f"({len(result.rows)} {noun})", file=out)
    else:
        print(result.message, file=out)
    return result


def run_script_file(engine, path, out):
    if path == "-":
        text = sys.stdin.read()
    else:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    count = 0
    results = engine.execute_script(text)
    for result in results:
        if result.statement_type == "SELECT":
            print(render_table(result.columns, result.rows), file=out)
            noun = "row" if len(result.rows) == 1 else "rows"
            print(f"({len(result.rows)} {noun})", file=out)
        else:
            print(result.message, file=out)
        count += 1
    return count


def run_repl(engine, instream, outstream):
    print("sqlq interactive shell.  Type SQL ending with ';' or .help for help.",
          file=outstream)
    buffer = ""
    while True:
        prompt = "sqlq> " if not buffer else "  ...> "
        print(prompt, end="", file=outstream)
        outstream.flush()
        line = instream.readline()
        if line == "":
            if buffer.strip():
                _run_buffer(engine, buffer, outstream)
            print(file=outstream)
            return 0
        line = line.rstrip("\n")
        stripped = line.strip()
        if not buffer and stripped.startswith("."):
            action = _handle_meta(engine, stripped, outstream)
            if action == "exit":
                return 0
            continue
        buffer += line + "\n"
        if stripped.endswith(";"):
            buffer = _run_buffer(engine, buffer, outstream)


def _run_buffer(engine, buffer, outstream):
    try:
        # The REPL permits several statements pasted at once.
        results = engine.execute_script(buffer)
    except SqlqError as error:
        print(f"Error: {error}", file=outstream)
        return ""
    for result in results:
        if result.statement_type == "SELECT":
            print(render_table(result.columns, result.rows), file=outstream)
            noun = "row" if len(result.rows) == 1 else "rows"
            print(f"({len(result.rows)} {noun})", file=outstream)
        else:
            print(result.message, file=outstream)
    return ""


def _handle_meta(engine, line, outstream):
    command = line.split(maxsplit=1)[0].lower()
    if command in (".quit", ".exit"):
        return "exit"
    if command == ".help":
        print(
            "Commands:\n"
            "  .tables          list tables\n"
            "  .schema [TABLE]  show CREATE TABLE definition\n"
            "  .exit / .quit    leave the shell\n"
            "Otherwise enter SQL terminated by ';'.",
            file=outstream,
        )
    elif command == ".tables":
        names = engine.table_names()
        print("\n".join(names) if names else "(no tables)", file=outstream)
    elif command == ".schema":
        parts = line.split(maxsplit=1)
        if len(parts) == 1:
            for name in engine.table_names():
                _print_schema(engine, name, outstream)
        else:
            name = parts[1].strip()
            if name not in engine.tables:
                print(f"Error: unknown table {name!r}", file=outstream)
            else:
                _print_schema(engine, name, outstream)
    else:
        print(f"Error: unknown meta command {command!r} (.help for help)",
              file=outstream)
    return None


def _print_schema(engine, name, outstream):
    table = engine.tables[name]
    defs = []
    for column in table.columns:
        suffix = " PRIMARY KEY" if column.primary_key else ""
        defs.append(f"  {column.name} {column.data_type}{suffix}")
    print(f"CREATE TABLE {name} (\n" + ",\n".join(defs) + "\n);",
          file=outstream)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="sqlq", description="A tiny in-memory SQL query engine."
    )
    parser.add_argument(
        "files", nargs="*",
        help="SQL files to execute. Use '-' to read from standard input.",
    )
    args = parser.parse_args(argv)
    engine = Engine()
    out = sys.stdout
    if args.files:
        try:
            for path in args.files:
                run_script_file(engine, path, out)
        except OSError as error:
            print(f"Error: cannot read {path}: {error}", file=sys.stderr)
            return 1
        except SqlqError as error:
            print(f"Error: {error}", file=sys.stderr)
            return 1
        return 0
    return run_repl(engine, sys.stdin, out)


if __name__ == "__main__":
    sys.exit(main())
