"""命令行入口: minipb compile schema.mpb -o schema_pb.py"""

import argparse
import sys

from .codegen import generate
from .errors import SchemaError
from .schema import parse_schema


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="minipb", description="A mini Protocol Buffers compiler"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    compile_parser = sub.add_parser("compile", help="compile a .mpb schema to Python")
    compile_parser.add_argument("schema", help="path to the .mpb schema file")
    compile_parser.add_argument(
        "-o", "--output", required=True, help="output .py file path"
    )
    args = parser.parse_args(argv)

    if args.command == "compile":
        return _compile(args.schema, args.output)
    return 1  # pragma: no cover


def _compile(schema_path, output_path):
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        print("minipb: cannot read %s: %s" % (schema_path, exc), file=sys.stderr)
        return 1
    try:
        schema = parse_schema(text)
    except SchemaError as exc:
        print("minipb: %s: %s" % (schema_path, exc), file=sys.stderr)
        return 1
    code = generate(schema, source_name=schema_path)
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(code)
    except OSError as exc:
        print("minipb: cannot write %s: %s" % (output_path, exc), file=sys.stderr)
        return 1
    print("minipb: wrote %s" % output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
