"""Command line interface for the rex regex engine.

Examples::

    rex-cli '\\d+' 'order 42 and 7'
    echo 'a1 b2' | rex-cli '(\\w)(\\d)' --findall
    rex-cli '^foo' --multiline --file notes.txt
"""

import argparse
import sys

from . import compile
from .errors import RegexError
from . import flags as _flags


def build_parser():
    parser = argparse.ArgumentParser(
        prog="rex-cli",
        description="Search text with a rex regular expression (stdlib-only engine).",
    )
    parser.add_argument("pattern", nargs="?", help="regular expression pattern")
    parser.add_argument("text", nargs="?", help="text to search (default: stdin)")
    parser.add_argument("--ignore-case", "-i", action="store_true", help="case insensitive match")
    parser.add_argument("--multiline", "-m", action="store_true", help="^/$ match line edges")
    parser.add_argument(
        "--findall",
        action="store_true",
        help="print one extracted result per line (groups when present)",
    )
    parser.add_argument("--file", metavar="PATH", help="read text from file PATH")
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="per-match step budget (default 100000000)",
    )
    parser.add_argument(
        "--count",
        action="store_true",
        help="print only the number of matches",
    )
    parser.add_argument(
        "--pattern-file",
        metavar="PATH",
        help="read the pattern (first line) from file PATH",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    stdin_tail = None
    if args.pattern is not None:
        pattern = args.pattern
    elif args.pattern_file:
        with open(args.pattern_file, "r", encoding="utf-8") as fh:
            pattern = fh.readline().rstrip("\n")
    else:
        if sys.stdin.isatty():
            parser.error("a pattern is required unless stdin supplies it")
        first = sys.stdin.readline()
        pattern = first.rstrip("\n")
        stdin_tail = sys.stdin.read()

    if args.text is not None:
        text = args.text
    elif args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            text = fh.read()
    elif stdin_tail is not None:
        text = stdin_tail
    else:
        text = sys.stdin.read()

    flags = 0
    if args.ignore_case:
        flags |= _flags.IGNORECASE
    if args.multiline:
        flags |= _flags.MULTILINE

    try:
        kwargs = {}
        if args.max_steps is not None:
            kwargs["max_steps"] = args.max_steps
        compiled = compile(pattern, flags, **kwargs)
    except RegexError as exc:
        print("rex: invalid pattern: %s" % exc, file=sys.stderr)
        return 2

    try:
        if args.findall:
            found = compiled.findall(text)
            if not args.count:
                for item in found:
                    if isinstance(item, tuple):
                        print("\t".join("" if v is None else v for v in item))
                    else:
                        print(item)
            print("matches: %d" % len(found), file=sys.stderr)
            return 0

        matches = list(compiled.finditer(text))
    except RegexError as exc:
        print("rex: match failed: %s" % exc, file=sys.stderr)
        return 3
    if args.count:
        print(len(matches))
        return 0

    if not matches:
        print("no matches", file=sys.stderr)
        return 0

    out = sys.stdout
    for match in matches:
        out.write("match at %d-%d: %r\n" % (match.start(), match.end(), match.group()))
        # Capturing groups in opening parenthesis order.
        for slot in range(compiled._program.group_count):
            label = None
            for name, name_slot in compiled._name_slots.items():
                if name_slot == slot:
                    label = name
                    break
            ms, me = match._caps[2 * slot], match._caps[2 * slot + 1]
            if ms is None:
                value = None
            else:
                value = text[ms:me]
            if label is not None:
                out.write("  group <%s>: %r\n" % (label, value))
            else:
                num = None
                for candidate, candidate_slot in compiled._num_slots.items():
                    if candidate_slot == slot:
                        num = candidate
                        break
                out.write("  group %d: %r\n" % (num, value))
    out.write("matches: %d\n" % len(matches))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
