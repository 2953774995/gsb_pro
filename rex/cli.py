"""rex-cli: command line interface for the rex regex engine.

Usage examples::

    rex-cli '(\\w+)@(\\w+)' 'contact alice@example.org'
    echo 'hello world' | rex-cli -i 'HELLO'
    rex-cli --findall '\\d+' --file data.txt
"""

import argparse
import sys

from . import __version__
from .errors import RegexError
from .flags import IGNORECASE, MULTILINE
from .pattern import compile as _compile


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="rex-cli",
        description="Search text with the rex mini regex engine.",
    )
    parser.add_argument("pattern", help="the regular expression to search for")
    parser.add_argument(
        "text",
        nargs="?",
        default=None,
        help="text to search (omit to read from stdin, or use --file)",
    )
    parser.add_argument(
        "-i", "--ignore-case",
        action="store_true",
        help="case-insensitive matching",
    )
    parser.add_argument(
        "-m", "--multiline",
        action="store_true",
        help="^ and $ match at line boundaries",
    )
    parser.add_argument(
        "--findall",
        action="store_true",
        help="list every non-overlapping match",
    )
    parser.add_argument(
        "--file",
        metavar="PATH",
        default=None,
        help="read the text to search from a file",
    )
    parser.add_argument(
        "--step-limit",
        type=int,
        default=None,
        help="per-match step budget (default: 100000000)",
    )
    parser.add_argument(
        "--version", action="version", version="rex %s" % __version__
    )
    return parser


def _read_text(args, parser):
    if args.file is not None:
        try:
            with open(args.file, "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError as exc:
            parser.error("cannot read %s: %s" % (args.file, exc))
    if args.text is not None:
        return args.text
    if not sys.stdin.isatty():
        return sys.stdin.read()
    parser.error("no input text: pass TEXT, use --file, or pipe via stdin")


def _print_match(index, match, out):
    start, end = match.span()
    print(
        "match %d: span=(%d, %d) text=%r" % (index, start, end, match.group(0)),
        file=out,
    )
    for gi in range(1, match.re.groups + 1):
        print(
            "  group %d: %r %s" % (gi, match.group(gi), match.span(gi)),
            file=out,
        )
    for name, value in match.groupdict().items():
        print(
            "  group %r: %r %s" % (name, value, match.span(name)),
            file=out,
        )


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)

    flags = 0
    if args.ignore_case:
        flags |= IGNORECASE
    if args.multiline:
        flags |= MULTILINE

    kwargs = {}
    if args.step_limit is not None:
        kwargs["step_limit"] = args.step_limit

    try:
        pattern = _compile(args.pattern, flags, **kwargs)
    except RegexError as exc:
        print("rex-cli: invalid pattern: %s" % exc, file=sys.stderr)
        return 2

    text = _read_text(args, parser)

    try:
        if args.findall:
            matches = list(pattern.finditer(text))
        else:
            first = pattern.search(text)
            matches = [first] if first is not None else []
    except RegexError as exc:
        print("rex-cli: match failed: %s" % exc, file=sys.stderr)
        return 3

    for index, match in enumerate(matches, 1):
        _print_match(index, match, sys.stdout)
    print("total matches: %d" % len(matches))
    return 0 if matches else 1


if __name__ == "__main__":
    raise SystemExit(main())
