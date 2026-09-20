"""Command line interface: zipmini c|x|l."""

from __future__ import annotations

import argparse
import os
import sys

from .archive import ZipError, ZipReader, ZipWriter


def _cmd_create(args: argparse.Namespace) -> int:
    with ZipWriter(args.archive, compresslevel=args.level) as zw:
        for item in args.files:
            if not os.path.exists(item):
                print(f"zipmini: no such file or directory: {item}", file=sys.stderr)
                return 1
            zw.write(item)
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    try:
        reader = ZipReader(args.archive)
    except ZipError as exc:
        print(f"zipmini: {exc}", file=sys.stderr)
        return 1
    dest = args.directory
    os.makedirs(dest, exist_ok=True)
    try:
        written = reader.extractall(dest)
    except ZipError as exc:
        print(f"zipmini: {exc}", file=sys.stderr)
        return 1
    for path in written:
        print(f"  extracted: {path}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    try:
        reader = ZipReader(args.archive)
    except ZipError as exc:
        print(f"zipmini: {exc}", file=sys.stderr)
        return 1
    members = reader.infolist()
    print(f"Archive: {args.archive}")
    print(f"{'Length':>12} {'Method':>8} {'Size':>12} {'Ratio':>7}  Name")
    total_unc = total_cmp = 0
    for m in members:
        method = {0: "Stored", 8: "Defl:N"}.get(m.compress_type, str(m.compress_type))
        ratio = f"{m.compress_ratio * 100:6.1f}%" if not m.is_dir else "    - "
        print(f"{m.uncompressed_size:>12} {method:>8} {m.compressed_size:>12} {ratio}  {m.filename}")
        total_unc += m.uncompressed_size
        total_cmp += m.compressed_size
    ratio = f"{(1 - total_cmp / total_unc) * 100:6.1f}%" if total_unc else "    - "
    print("-" * 64)
    print(f"{total_unc:>12} {'':>8} {total_cmp:>12} {ratio}  {len(members)} file(s)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zipmini",
        description="Minimal zip archiver with a from-scratch DEFLATE implementation.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("c", help="create an archive")
    p_create.add_argument("archive", help="output .zip path")
    p_create.add_argument("files", nargs="+", help="files/directories to add")
    p_create.add_argument("-l", "--level", type=int, default=6, choices=range(1, 10),
                          help="compression effort 1-9 (default 6)")
    p_create.set_defaults(func=_cmd_create)

    p_extract = sub.add_parser("x", help="extract an archive")
    p_extract.add_argument("archive", help="input .zip path")
    p_extract.add_argument("-d", "--directory", default=".", help="output directory")
    p_extract.set_defaults(func=_cmd_extract)

    p_list = sub.add_parser("l", help="list archive contents")
    p_list.add_argument("archive", help="input .zip path")
    p_list.set_defaults(func=_cmd_list)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
