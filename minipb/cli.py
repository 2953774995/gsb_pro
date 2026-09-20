"""minipb 命令行入口：minipb compile schema.mpb -o out_pb.py"""

import argparse
import sys

from .compiler import compile_schema
from .errors import SchemaError
from .schema import parse


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="minipb", description="迷你版 Protocol Buffers 编译器")
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("compile", help="编译 .mpb schema 为 Python 模块")
    c.add_argument("schema", help="输入的 .mpb schema 文件")
    c.add_argument("-o", "--output", required=True, help="输出的 .py 文件")
    args = parser.parse_args(argv)

    if args.command == "compile":
        try:
            with open(args.schema, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            print("minipb: 无法读取 %s: %s" % (args.schema, e), file=sys.stderr)
            return 1
        try:
            schema = parse(text)
        except SchemaError as e:
            print("%s: %s" % (args.schema, e), file=sys.stderr)
            return 1
        code = compile_schema(schema, source=args.schema)
        try:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(code)
        except OSError as e:
            print("minipb: 无法写入 %s: %s" % (args.output, e), file=sys.stderr)
            return 1
        print("minipb: 已生成 %s" % args.output)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
