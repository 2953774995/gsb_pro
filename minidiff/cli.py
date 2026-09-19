"""Command-line interface for minidiff."""

import argparse
import sys

from .exceptions import DiffError
from .patch import apply_patch
from .unified import unified_diff as _unified_diff
from .diff import similarity as _similarity


def _read(path):
    if path == "-":
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def build_parser():
    parser = argparse.ArgumentParser(
        prog="minidiff",
        description="Compute unified diffs and apply patches "
                    "(pure standard-library implementation).",
    )
    sub = parser.add_subparsers(dest="command")

    diff_p = sub.add_parser("diff", help="print a unified diff "
                                         "(default subcommand)")
    diff_p.add_argument("original")
    diff_p.add_argument("revised")
    diff_p.add_argument("-U", "--unified", type=int, default=3,
                        metavar="CONTEXT",
                        help="number of context lines (default: 3)")

    apply_p = sub.add_parser("apply", help="apply a unified diff")
    apply_p.add_argument("patch", help="path of the .diff/.patch file")
    apply_p.add_argument("original", help="file to patch")
    apply_p.add_argument("-R", "--reverse", action="store_true",
                         help="apply the patch in reverse")
    apply_p.add_argument("--fuzz", nargs="?", const=True, default=False,
                         metavar="RADIUS",
                         help="allow shifted hunks; optional max distance")
    apply_p.add_argument("-o", "--output",
                         help="write result here instead of stdout")

    stat_p = sub.add_parser("similarity", help="print line similarity ratio")
    stat_p.add_argument("original")
    stat_p.add_argument("revised")

    return parser


def main(argv=None):
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    # Accept "minidiff --apply patch original" as an alias of the apply
    # subcommand, and bare "minidiff a.txt b.txt" as the diff subcommand.
    if argv and argv[0] == "--apply":
        argv = ["apply"] + argv[1:]
    if argv and argv[0] not in ("diff", "apply", "similarity",
                                "-h", "--help"):
        argv = ["diff"] + argv
    args = parser.parse_args(argv)

    try:
        if args.command in (None, "diff"):
            if args.command is None:
                parser.print_help()
                return 0
            a = _read(args.original)
            b = _read(args.revised)
            text = _unified_diff(a, b,
                                 fromfile=args.original,
                                 tofile=args.revised,
                                 context=args.unified)
            sys.stdout.write(text)
            return 0
        if args.command == "apply":
            patch_text = _read(args.patch)
            text = _read(args.original)
            fuzz = args.fuzz
            if isinstance(fuzz, str):
                try:
                    fuzz = int(fuzz)
                except ValueError:
                    raise DiffError("--fuzz radius must be an integer")
                if fuzz < 0:
                    raise DiffError("--fuzz radius must be non-negative")
            result = apply_patch(text, patch_text,
                                 reverse=args.reverse, fuzz=fuzz)
            if args.output:
                with open(args.output, "w", encoding="utf-8",
                          newline="") as handle:
                    handle.write(result)
            else:
                sys.stdout.write(result)
            return 0
        if args.command == "similarity":
            a = _read(args.original)
            b = _read(args.revised)
            sys.stdout.write("%.6f\n" % _similarity(a, b))
            return 0
    except (DiffError, OSError) as exc:
        sys.stderr.write("minidiff: error: %s\n" % exc)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
