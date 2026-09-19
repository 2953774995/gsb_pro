"""Command line interface for minidiff."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .patch import DiffError, apply_patch
from .unified import unified_diff


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="minidiff",
        description="Compute unified diffs or apply a unified patch using minidiff.",
    )
    parser.add_argument(
        "--context",
        "-c",
        type=int,
        default=3,
        help="number of context lines for generated diffs (default: 3)",
    )
    parser.add_argument(
        "--apply",
        metavar="PATCH",
        help="apply PATCH to the original file supplied as a positional argument",
    )
    parser.add_argument(
        "--reverse",
        "-R",
        action="store_true",
        help="apply the patch in reverse",
    )
    parser.add_argument(
        "--no-fuzz",
        action="store_true",
        help="require each hunk to occur at the exact patched line number",
    )
    parser.add_argument(
        "--output",
        "-o",
        metavar="FILE",
        help="write the result to FILE instead of standard output",
    )
    parser.add_argument(
        "files",
        nargs="+",
        metavar="FILE",
        help="two files for a diff, or the original file when --apply is used",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.apply is not None:
            if len(args.files) != 1:
                parser.error("--apply requires exactly one original file")
            original = Path(args.files[0]).read_text(encoding="utf-8")
            patch_text = Path(args.apply).read_text(encoding="utf-8")
            result = apply_patch(
                original,
                patch_text,
                reverse=args.reverse,
                fuzz=not args.no_fuzz,
            )
        else:
            if len(args.files) != 2:
                parser.error("a diff requires exactly two files")
            if args.context < 0:
                parser.error("--context must be non-negative")
            old_text = Path(args.files[0]).read_text(encoding="utf-8")
            new_text = Path(args.files[1]).read_text(encoding="utf-8")
            result = unified_diff(
                old_text,
                new_text,
                context=args.context,
                fromfile=args.files[0],
                tofile=args.files[1],
            )

        if args.output:
            Path(args.output).write_text(result, encoding="utf-8")
        else:
            sys.stdout.write(result)
        return 0
    except (OSError, DiffError, ValueError) as exc:
        print(f"minidiff: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
