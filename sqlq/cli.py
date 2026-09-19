"""Command line interface for sqlq.

Usage:
    sqlq-cli [file.sql]      # execute a script file
    echo "SQL;" | sqlq-cli   # execute statements piped on stdin
    sqlq-cli                 # start the interactive REPL
"""

import argparse
import sys
import unicodedata

from .errors import SqlqError
from .executor import Engine
from .lexer import tokenize


PROMPT_FIRST = "sqlq> "
PROMPT_MORE = " ...> "


def display_width(text):
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def pad(text, width):
    return text + " " * (width - display_width(text))


def render_cell(text, width):
    # One space of padding on each side plus width-based alignment.
    return " " + text + " " * (width - display_width(text) + 1)


def format_value(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    return str(value)


def render_table(columns, rows):
    rendered_rows = [[format_value(value) for value in row] for row in rows]
    widths = [display_width(name) for name in columns]
    for row in rendered_rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], display_width(cell))

    border = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
    lines = [border]
    lines.append("|" + "|".join(
        render_cell(name, widths[index]) for index, name in enumerate(columns)) + "|")
    lines.append(border)
    for row in rendered_rows:
        lines.append("|" + "|".join(
            render_cell(value, widths[index])
            for index, value in enumerate(row)) + "|")
    lines.append(border)
    return "\n".join(lines)


def print_result(result, out):
    if result.statement == "SELECT":
        if result.columns:
            out.write(render_table(result.columns, result.rows) + "\n")
        out.write(result.tag + "\n")
    else:
        out.write(result.tag + "\n")


def is_complete_statement(buffer):
    """A buffer is complete when its final meaningful token is ';'."""
    stripped = buffer.strip()
    if not stripped:
        return False
    try:
        tokens = tokenize(buffer)
    except SqlqError:
        # Let the parser surface the precise error.
        return stripped.endswith(";")
    meaningful = [token for token in tokens if token.kind != "EOF"]
    return bool(meaningful) and meaningful[-1].kind == "PUNCT" \
        and meaningful[-1].value == ";"


def run_script(engine, text, out):
    results = engine.execute_script(text)
    for result in results:
        print_result(result, out)
    return len(results)


def run_repl(engine, in_stream, out):
    out.write("sqlq interactive shell. Type SQL statements terminated by ;\n"
              "Meta commands: .tables, .schema [TABLE], .help, .exit\n")
    out.flush()
    buffer = ""

    while True:
        try:
            line = in_stream.readline()
        except (EOFError, KeyboardInterrupt):
            out.write("\n")
            break
        if line == "":
            out.write("\n")
            break

        stripped_line = line.strip()
        if not buffer:
            if stripped_line in (".exit", ".quit"):
                break
            if stripped_line == ".help":
                out.write(".tables             list tables\n"
                          ".schema [TABLE]     show table definitions\n"
                          ".exit / .quit       leave the shell\n")
                out.flush()
                continue
            if stripped_line == ".tables":
                names = sorted(table.name for table in engine.tables.values())
                out.write("\n".join(names) + ("\n" if names else ""))
                out.flush()
                continue
            if stripped_line.startswith(".schema"):
                parts = stripped_line.split()
                target = parts[1] if len(parts) > 1 else None
                for table in engine.tables.values():
                    if target is not None and \
                            table.name.lower() != target.lower():
                        continue
                    defs = []
                    for column in table.columns:
                        piece = "{} {}".format(column.name, column.type_name)
                        if column.primary_key:
                            piece += " PRIMARY KEY"
                        defs.append(piece)
                    out.write("CREATE TABLE {} ({});\n"
                              .format(table.name, ", ".join(defs)))
                out.flush()
                continue

        buffer += line
        if not is_complete_statement(buffer):
            out.write(PROMPT_MORE if buffer.strip() else PROMPT_FIRST)
            out.flush()
            continue

        try:
            run_script(engine, buffer, out)
        except SqlqError as error:
            out.write("Error: {}\n".format(error))
        finally:
            buffer = ""
        out.write(PROMPT_FIRST)
        out.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="sqlq-cli",
        description="Run SQL statements with the in-memory sqlq engine.")
    parser.add_argument("filename", nargs="?",
                        help="SQL script to execute; without it sqlq-cli "
                             "reads stdin or starts an interactive shell")
    args = parser.parse_args(argv)

    engine = Engine()

    if args.filename:
        try:
            with open(args.filename, "r", encoding="utf-8") as handle:
                text = handle.read()
        except OSError as error:
            sys.stderr.write("Error: cannot read '{}': {}\n"
                             .format(args.filename, error))
            return 1
        try:
            run_script(engine, text, sys.stdout)
        except SqlqError as error:
            sys.stderr.write("Error: {}\n".format(error))
            return 1
        return 0

    if sys.stdin.isatty():
        sys.stdout.write(PROMPT_FIRST)
        sys.stdout.flush()
        run_repl(engine, sys.stdin, sys.stdout)
        return 0

    text = sys.stdin.read()
    if text.strip():
        try:
            run_script(engine, text, sys.stdout)
        except SqlqError as error:
            sys.stderr.write("Error: {}\n".format(error))
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
