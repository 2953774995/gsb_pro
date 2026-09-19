"""Command line interface: render a template file with JSON data.

Usage:
    tinytpl-cli template.html data.json [--strict]
    python3 -m tinytpl.cli template.html data.json
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
        description="Render a tinytpl template with data from a JSON file. "
        "extends/include are resolved relative to the template's directory.",
    )
    parser.add_argument("template", help="path to the template file")
    parser.add_argument("data", help="path to a JSON file with render context")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="raise an error on missing variables instead of rendering ''",
    )
    args = parser.parse_args(argv)

    try:
        with open(args.data, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        print("tinytpl-cli: cannot read data file: %s" % exc, file=sys.stderr)
        return 2
    if not isinstance(data, dict):
        print("tinytpl-cli: JSON data must be an object", file=sys.stderr)
        return 2

    directory = os.path.dirname(os.path.abspath(args.template))
    env = Environment(loader=FileSystemLoader(directory), strict=args.strict)
    try:
        template = env.get_template(os.path.basename(args.template))
        output = template.render(data)
    except TplError as exc:
        print("tinytpl-cli: error: %s" % exc, file=sys.stderr)
        return 1

    sys.stdout.write(output)
    if not output.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
