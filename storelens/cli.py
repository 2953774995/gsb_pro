"""Interactive command-line interface for storelens.

Usage:
    storelens-cli                start an interactive session
    storelens-cli script.sql     execute all statements in a file
    storelens-cli -f script.sql  same as above

Interactive meta-commands:
    .help                 show help
    .tables               list datasets
    .schema TABLE         show column definitions of a dataset
    .import TABLE FILE    bulk-import a JSON file into a dataset
    .read FILE            execute statements from a file
    .exit / .quit         leave the session
"""

import sys

from .engine import Engine
from .errors import StorelensError

BANNER = ("storelens %s -- local store-operations data analyzer\n"
          "Type .help for help, .exit to quit.")
PROMPT = "storelens> "
CONTINUATION = "       ... "

HELP_TEXT = """\
Statements (must end with ';'):
  CREATE TABLE name (col TYPE [PRIMARY KEY], ...);   TYPE: INTEGER|REAL|TEXT
  DROP TABLE name;
  INSERT INTO name [(cols)] VALUES (...), (...);
  UPDATE name SET col = expr [, ...] [WHERE expr];
  DELETE FROM name [WHERE expr];
  SELECT [DISTINCT] expr [AS alias], ... FROM name
    [WHERE expr] [GROUP BY expr, ...] [HAVING expr]
    [ORDER BY expr [ASC|DESC], ...] [LIMIT n [OFFSET m]];

Meta-commands:
  .help                 show this help
  .tables               list datasets
  .schema TABLE         show column definitions
  .import TABLE FILE    import a JSON array of row objects into TABLE
  .read FILE            execute statements from a file
  .exit                 quit
"""


def format_value(value):
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return "%g" % value
    return str(value)


def format_table(result):
    """Render a Result as an aligned text table."""
    lines = []
    if result.columns:
        str_rows = [[format_value(v) for v in row] for row in result.rows]
        widths = [len(c) for c in result.columns]
        for row in str_rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(cell))
        header = " | ".join(c.ljust(widths[i])
                            for i, c in enumerate(result.columns))
        sep = "-+-".join("-" * w for w in widths)
        lines.append(header)
        lines.append(sep)
        for row in str_rows:
            lines.append(" | ".join(cell.ljust(widths[i])
                                    for i, cell in enumerate(row)))
        lines.append("(%d row%s)" % (len(result.rows),
                                     "s" if len(result.rows) != 1 else ""))
    elif result.message:
        lines.append(result.message)
    return "\n".join(lines)


def print_result(result, out=None):
    text = format_table(result)
    if text:
        print(text, file=out if out is not None else sys.stdout)


class Shell:
    def __init__(self, engine=None, out=None):
        self.engine = engine or Engine()
        self.out = out if out is not None else sys.stdout

    # -- meta commands ------------------------------------------------------

    def handle_meta(self, line):
        parts = line.strip().split()
        cmd = parts[0].lower()
        args = parts[1:]
        if cmd in (".exit", ".quit"):
            return False
        if cmd == ".help":
            print(HELP_TEXT, file=self.out)
        elif cmd == ".tables":
            names = self.engine.tables
            print("\n".join(names) if names else "(no datasets)",
                  file=self.out)
        elif cmd == ".schema":
            if not args:
                print("Usage: .schema TABLE", file=self.out)
            else:
                table = self.engine.get_table(args[0])
                for col in table.columns:
                    suffix = " PRIMARY KEY" if col.primary_key else ""
                    print("  %s %s%s" % (col.name, col.type_name, suffix),
                          file=self.out)
        elif cmd == ".import":
            if len(args) != 2:
                print("Usage: .import TABLE FILE", file=self.out)
            else:
                count = self.engine.import_json(args[0], args[1])
                print("%d row(s) imported into '%s'" % (count, args[0]),
                      file=self.out)
        elif cmd == ".read":
            if len(args) != 1:
                print("Usage: .read FILE", file=self.out)
            else:
                self.run_file(args[0])
        else:
            print("Unknown command %r -- type .help" % cmd, file=self.out)
        return True

    # -- execution ------------------------------------------------------------

    def run_text(self, text):
        """Execute a script and print every result.

        Lines starting with '.' are treated as meta-commands, so batch
        files may mix SQL statements with e.g. .import directives.
        """
        buffer = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(".") and not "".join(buffer).strip():
                buffer = []
                self.handle_meta(stripped)
                continue
            buffer.append(line)
            if ";" in line:
                chunk = "\n".join(buffer)
                buffer = []
                for result in self.engine.execute_script(chunk):
                    print_result(result, self.out)
        rest = "\n".join(buffer).strip()
        if rest:
            for result in self.engine.execute_script(rest):
                print_result(result, self.out)

    def run_file(self, path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except FileNotFoundError:
            raise StorelensError("File not found: %s" % path)
        self.run_text(text)

    def repl(self):
        print(BANNER % _version(), file=self.out)
        buffer = ""
        while True:
            try:
                line = input(CONTINUATION if buffer else PROMPT)
            except EOFError:
                print("", file=self.out)
                break
            except KeyboardInterrupt:
                print("", file=self.out)
                buffer = ""
                continue
            stripped = line.strip()
            if not buffer and not stripped:
                continue
            if not buffer and stripped.startswith("."):
                try:
                    if not self.handle_meta(stripped):
                        break
                except StorelensError as exc:
                    print("Error: %s" % exc, file=self.out)
                continue
            buffer += line + "\n"
            if ";" not in buffer:
                continue
            text, buffer = buffer, ""
            try:
                self.run_text(text)
            except StorelensError as exc:
                print("Error: %s" % exc, file=self.out)


def _version():
    from . import __version__
    return __version__


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    shell = Shell()
    script = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-f", "--file"):
            i += 1
            if i >= len(argv):
                print("storelens-cli: -f requires a file argument",
                      file=sys.stderr)
                return 2
            script = argv[i]
        elif arg in ("-h", "--help"):
            print(__doc__)
            return 0
        elif arg.startswith("-"):
            print("storelens-cli: unknown option %s" % arg, file=sys.stderr)
            return 2
        else:
            script = arg
        i += 1
    if script is not None:
        try:
            shell.run_file(script)
        except StorelensError as exc:
            print("Error: %s" % exc, file=sys.stderr)
            return 1
        return 0
    try:
        shell.repl()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
