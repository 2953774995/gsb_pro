"""Command line interface: zipmini c|x|l."""

import argparse
import os
import sys

from . import zipcontainer
from .zipcontainer import ZipError


def _arcname(path):
    """Normalise a filesystem path into a zip member name."""
    name = os.path.normpath(path)
    drive, name = os.path.splitdrive(name)
    name = name.strip(os.sep).replace(os.sep, "/")
    if name in ("", "."):
        name = os.path.basename(os.path.abspath(path))
    return name


def _gather(paths):
    """Expand files/directories into (arcname, data, mtime) items."""
    items = []
    for p in paths:
        if not os.path.exists(p):
            raise ZipError("no such file or directory: %s" % p)
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                root_arc = _arcname(root)
                items.append((root_arc + "/", b"",
                              os.path.getmtime(root)))
                for fn in sorted(files):
                    full = os.path.join(root, fn)
                    with open(full, "rb") as f:
                        data = f.read()
                    items.append((_arcname(full), data,
                                  os.path.getmtime(full)))
        else:
            with open(p, "rb") as f:
                data = f.read()
            items.append((_arcname(p), data, os.path.getmtime(p)))
    return items


def cmd_create(args):
    items = _gather(args.files)
    zipcontainer.write_zip(args.archive, items)
    n_files = sum(1 for n, _d, _m in items if not n.endswith("/"))
    print("created %s (%d file%s)" %
          (args.archive, n_files, "" if n_files == 1 else "s"))


def _safe_join(dest, name):
    """Join a member name onto dest, refusing path traversal."""
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ZipError("unsafe path in archive: %r" % name)
    return os.path.join(dest, *parts) if parts else None


def cmd_extract(args):
    entries = zipcontainer.read_zip_directory(args.archive)
    dest = args.dest
    os.makedirs(dest, exist_ok=True)
    count = 0
    for info in entries:
        target = _safe_join(dest, info.name)
        if target is None:
            continue
        if info.is_dir:
            os.makedirs(target, exist_ok=True)
            continue
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        data = zipcontainer.read_file(args.archive, info)
        with open(target, "wb") as f:
            f.write(data)
        os.utime(target, (info.mtime, info.mtime))
        count += 1
    print("extracted %d file%s to %s" %
          (count, "" if count == 1 else "s", dest))


def cmd_list(args):
    entries = zipcontainer.read_zip_directory(args.archive)
    print("%10s  %10s  %6s  %s" % ("Length", "Compressed", "Ratio", "Name"))
    print("%10s  %10s  %6s  %s" % ("-" * 10, "-" * 10, "-" * 6, "-" * 4))
    total = total_c = 0
    for info in entries:
        if info.is_dir:
            print("%10d  %10s  %6s  %s" % (0, "-", "-", info.name))
            continue
        if info.file_size:
            ratio = "%5.1f%%" % (100.0 * (1.0 - info.compress_size /
                                          info.file_size))
        else:
            ratio = "  0.0%"
        print("%10d  %10d  %s  %s" % (info.file_size, info.compress_size,
                                      ratio, info.name))
        total += info.file_size
        total_c += info.compress_size
    print("%10s  %10s  %6s  %s" % ("-" * 10, "-" * 10, "-" * 6, "-" * 4))
    if total:
        ratio = "%5.1f%%" % (100.0 * (1.0 - total_c / total))
    else:
        ratio = "  0.0%"
    print("%10d  %10d  %s  %d file%s" %
          (total, total_c, ratio, len(entries),
           "" if len(entries) == 1 else "s"))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="zipmini",
        description="A minimal zip tool with a from-scratch DEFLATE "
                    "implementation.")
    sub = parser.add_subparsers(dest="command", required=True)

    pc = sub.add_parser("c", help="create an archive")
    pc.add_argument("archive", help="output .zip file")
    pc.add_argument("files", nargs="+", help="files/directories to add")
    pc.set_defaults(func=cmd_create)

    px = sub.add_parser("x", help="extract an archive")
    px.add_argument("archive", help="input .zip file")
    px.add_argument("-d", "--dest", default=".",
                    help="destination directory (default: .)")
    px.set_defaults(func=cmd_extract)

    pl = sub.add_parser("l", help="list archive contents")
    pl.add_argument("archive", help="input .zip file")
    pl.set_defaults(func=cmd_list)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except ZipError as exc:
        print("zipmini: error: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
