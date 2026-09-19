"""rex-cli: command-line interface to the rex regex engine."""
import argparse
import sys

import rex


def build_parser():
    p = argparse.ArgumentParser(
        prog="rex-cli",
        description="Search text with the rex mini regular-expression "
                    "engine.")
    p.add_argument("pattern", help="regular expression pattern")
    p.add_argument("text", nargs="?", default=None,
                   help="text to search (default: read from stdin, or "
                        "from --file)")
    p.add_argument("-i", "--ignore-case", action="store_true",
                   help="case-insensitive matching")
    p.add_argument("-m", "--multiline", action="store_true",
                   help="^ and $ match at line boundaries")
    p.add_argument("--findall", action="store_true",
                   help="print findall() results instead of match details")
    p.add_argument("-f", "--file", metavar="PATH",
                   help="read the text to search from PATH")
    p.add_argument("--max-steps", type=int, default=None,
                   help="per-match step limit (default: {})".format(
                       rex.DEFAULT_MAX_STEPS))
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    flags = 0
    if args.ignore_case:
        flags |= rex.IGNORECASE
    if args.multiline:
        flags |= rex.MULTILINE

    if args.file is not None:
        try:
            with open(args.file, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            print("rex-cli: cannot read {}: {}".format(args.file, exc),
                  file=sys.stderr)
            return 2
    elif args.text is not None:
        text = args.text
    else:
        text = sys.stdin.read()

    kwargs = {}
    if args.max_steps is not None:
        kwargs["max_steps"] = args.max_steps
    try:
        pattern = rex.compile(args.pattern, flags, **kwargs)
    except rex.RegexError as exc:
        print("rex-cli: invalid pattern: {}".format(exc), file=sys.stderr)
        return 2

    try:
        if args.findall:
            items = pattern.findall(text)
            for item in items:
                print(repr(item))
            print("{} match(es)".format(len(items)))
        else:
            count = 0
            for m in pattern.finditer(text):
                count += 1
                print("match {}: span={} text={!r}".format(
                    count, m.span(), m.group()))
                for i in range(1, pattern.groups + 1):
                    print("  group {}: {!r} span={}".format(
                        i, m.group(i), m.span(i)))
                for name in pattern.groupindex:
                    print("  group {}: {!r} span={}".format(
                        name, m.group(name), m.span(name)))
            print("{} match(es) found".format(count))
    except rex.RegexTimeoutError as exc:
        print("rex-cli: {}".format(exc), file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
