"""Command-line interface: ``regexlab-cli PATTERN TEXT``.

Prints whether the pattern matches the text, the matched substring and
the contents of every capturing group.
"""

import argparse
import sys

from .core import RegexError, compile


def _format(value):
    return "(no match)" if value is None else repr(value)


def build_arg_parser():
    parser = argparse.ArgumentParser(
        prog="regexlab-cli",
        description="Match a regex pattern against a text using the "
                    "regexlab engine (no 're' module involved).")
    parser.add_argument("pattern", help="the regular expression pattern")
    parser.add_argument("text", help="the text to match against")
    parser.add_argument(
        "--mode", choices=("search", "match", "fullmatch", "findall"),
        default="search",
        help="matching mode (default: search)")
    return parser


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    try:
        pattern = compile(args.pattern)
    except RegexError as exc:
        print("Pattern error: %s" % exc, file=sys.stderr)
        return 2

    print("pattern: %r" % args.pattern)
    print("text:    %r" % args.text)
    print("mode:    %s" % args.mode)

    if args.mode == "findall":
        results = pattern.findall(args.text)
        print("findall: %r" % (results,))
        return 0 if results else 1

    matcher = getattr(pattern, args.mode)
    m = matcher(args.text)
    if m is None:
        print("result:  NO MATCH")
        return 1
    print("result:  MATCH")
    print("span:    %s" % (m.span(),))
    print("matched: %r" % m.group(0))
    for i in range(1, pattern.groups + 1):
        print("group %d: %s" % (i, _format(m.group(i))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
