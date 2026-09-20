"""storelens command line interface.

Interactive REPL (statements end with ';') plus batch execution of a
script file. Meta commands start with a dot:

    .help                 show help
    .tables               list datasets
    .schema NAME          show dataset schema
    .import NAME FILE     bulk-import a JSON file into dataset NAME
    .quit / .exit         leave the REPL

Usage:
    storelens-cli                 start the interactive shell
    storelens-cli script.sql      execute a script file and exit
    python3 -m storelens          same as above
"""

import sys

from .engine import Engine
from .errors import StorelensError

PROMPT = "storelens> "
CONTINUATION = "   ...> "

HELP = """\
Statements (each must end with ';'):
  CREATE TABLE name (col TYPE [PRIMARY KEY], ...);   TYPE = INTEGER|REAL|TEXT
  DROP TABLE name;
  INSERT INTO name [(cols)] VALUES (...), (...);
  UPDATE name SET col = expr [, ...] [WHERE expr];
  DELETE FROM name [WHERE expr];
  SELECT [DISTINCT] expr [AS alias], ... FROM name
         [WHERE expr] [GROUP BY expr, ...] [HAVING expr]
         [ORDER BY expr [ASC|DESC], ...] [LIMIT n [OFFSET m]];

Meta commands:
  .help                 show this help
  .tables               list datasets
  .schema NAME          show dataset schema
  .import NAME FILE     import a JSON array of row objects into dataset NAME
  .quit                 exit
"""


def format_table(columns, rows):
    """Render a result set as an aligned text table."""
    def cell(value):
        if value is None:
            return "NULL"
        if isinstance(value, float):
            return "%g" % value
        return str(value)

    display = [[cell(v) for v in row] for row in rows]
    widths = []
    for idx, name in enumerate(columns):
        width = len(str(name))
        for row in display:
            width = max(width, len(row[idx]))
        widths.append(width)

    def fmt_row(values):
        return " | ".join(str(v).ljust(widths[i])
                          for i, v in enumerate(values))

    lines = [fmt_row(columns)]
    lines.append("-+-".join("-" * w for w in widths))
    lines.extend(fmt_row(row) for row in display)
    lines.append("(%d row%s)" % (len(rows), "" if len(rows) == 1 else "s"))
    return "\n".join(lines)


def print_result(result, out):
    if result.columns:
        out.write(format_table(result.columns, result.rows) + "\n")
    elif result.message:
        out.write(result.message + "\n")


def run_script(engine, text, out):
    """Execute a script statement by statement, printing each result.

    Stops at the first error. Returns True on success.
    """
    from .parser import parse
    try:
        statements = parse(text)
    except StorelensError as exc:
        out.write("Error: %s\n" % exc)
        return False
    for statement in statements:
        try:
            result = engine.execute_statement(statement)
        except StorelensError as exc:
            out.write("Error: %s\n" % exc)
            return False
        print_result(result, out)
    return True


def _handle_meta(engine, line, out):
    parts = line[1:].split()
    command = parts[0].lower() if parts else ""
    if command in ("quit", "exit"):
        return False
    if command == "help":
        out.write(HELP)
    elif command == "tables":
        names = sorted(engine.tables)
        if names:
            out.write("\n".join(names) + "\n")
        else:
            out.write("(no datasets)\n")
    elif command == "schema":
        if len(parts) != 2:
            out.write("usage: .schema NAME\n")
        else:
            table = engine.tables.get(parts[1])
            if table is None:
                out.write("Error: no such dataset (table): %s\n" % parts[1])
            else:
                for col in table.columns:
                    suffix = " PRIMARY KEY" if col.primary_key else ""
                    out.write("%s %s%s\n" % (col.name, col.type, suffix))
    elif command == "import":
        if len(parts) != 3:
            out.write("usage: .import NAME FILE\n")
        else:
            try:
                count = engine.import_json(parts[1], parts[2])
                out.write("%d row(s) imported into %s\n" % (count, parts[1]))
            except (StorelensError, OSError, ValueError) as exc:
                out.write("Error: %s\n" % exc)
    else:
        out.write("unknown command %r; try .help\n" % line)
    return True


def repl(engine=None, inp=None, out=None):
    engine = engine or Engine()
    inp = inp or sys.stdin
    out = out or sys.stdout
    out.write("storelens -- local store operations data analysis\n")
    out.write("type .help for help, .quit to exit\n")
    buffer = ""
    while True:
        try:
            if inp is sys.stdin:
                line = input(CONTINUATION if buffer else PROMPT)
            else:
                line = inp.readline()
                if line == "":
                    raise EOFError
                line = line.rstrip("\n")
        except EOFError:
            out.write("\n")
            break
        stripped = line.strip()
        if not buffer and not stripped:
            continue
        if not buffer and stripped.startswith("."):
            if not _handle_meta(engine, stripped, out):
                break
            continue
        buffer += line + "\n"
        if ";" not in line:
            continue
        run_script(engine, buffer, out)
        buffer = ""
    return engine


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    engine = Engine()
    if argv:
        path = argv[0]
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            sys.stderr.write("Error: cannot read %s: %s\n" % (path, exc))
            return 1
        return 0 if run_script(engine, text, sys.stdout) else 1
    repl(engine)
    return 0


if __name__ == "__main__":
    sys.exit(main())
