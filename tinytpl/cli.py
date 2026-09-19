"""tinytpl-cli：命令行渲染工具。

用法：
    tinytpl-cli template.html data.json [--strict]
    python3 -m tinytpl template.html data.json [--strict]

模板中的 extends/include 相对模板文件所在目录解析。
"""

import argparse
import json
import os
import sys

from .environment import Environment
from .errors import TplError
from .loader import FileSystemLoader


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="tinytpl-cli",
        description="Render a tinytpl template with a JSON data file.")
    parser.add_argument("template", help="模板文件路径")
    parser.add_argument("data", help="JSON 数据文件路径（顶层须为对象）")
    parser.add_argument("--strict", action="store_true",
                        help="严格模式：缺失变量时报错而不是渲染为空")
    args = parser.parse_args(argv)

    try:
        with open(args.data, "r", encoding="utf-8") as f:
            context = json.load(f)
    except OSError as exc:
        print("tinytpl-cli: cannot read data file: %s" % exc,
              file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print("tinytpl-cli: invalid JSON in %s: %s" % (args.data, exc),
              file=sys.stderr)
        return 2
    if not isinstance(context, dict):
        print("tinytpl-cli: JSON data must be an object at top level",
              file=sys.stderr)
        return 2

    template_dir = os.path.dirname(os.path.abspath(args.template))
    env = Environment(FileSystemLoader(template_dir), strict=args.strict)
    try:
        output = env.get_template(os.path.basename(args.template)) \
            .render(context)
    except TplError as exc:
        print("tinytpl-cli: %s" % exc, file=sys.stderr)
        return 1
    sys.stdout.write(output)
    if output and not output.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
