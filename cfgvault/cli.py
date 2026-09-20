"""Command-line entry point for cfgvault."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from . import __version__
from .commands import (
    cmd_add,
    cmd_branch,
    cmd_checkout,
    cmd_diff,
    cmd_init,
    cmd_log,
    cmd_reset,
    cmd_snap,
    cmd_status,
)
from .errors import CfgvaultError


def build_parser(err_stream=None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cfgvault",
        description="Snapshot and version-manage JSON promotion configurations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        conflict_handler="error",
    )
    parser.add_argument("--version", action="version", version=f"cfgvault {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    init_parser = subparsers.add_parser("init", help="create a .cfgvault repository")
    init_parser.add_argument("path", nargs="?", help="directory to initialize (default: current)")
    init_parser.set_defaults(func=cmd_init)

    add_parser = subparsers.add_parser("add", help="add files or directories to the index")
    add_parser.add_argument("paths", nargs="+", metavar="path", help="file or directory to add")
    add_parser.set_defaults(func=cmd_add)

    snap_parser = subparsers.add_parser("snap", help="create a snapshot from the index")
    snap_parser.add_argument("-m", "--message", required=True, help="snapshot description")
    snap_parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="create a snapshot even when the index matches HEAD",
    )
    snap_parser.add_argument("--operator", help="override operator identity")
    snap_parser.add_argument("--date", help="override timestamp (mainly for deterministic tests)")
    snap_parser.set_defaults(func=cmd_snap)

    log_parser = subparsers.add_parser("log", help="show snapshot history")
    log_parser.add_argument("--oneline", action="store_true", help="short hash and first line")
    log_parser.set_defaults(func=cmd_log)

    branch_parser = subparsers.add_parser("branch", help="list or create a scheme branch")
    branch_parser.add_argument("name", nargs="?", help="new scheme name")
    branch_parser.set_defaults(func=cmd_branch)

    checkout_parser = subparsers.add_parser("checkout", help="switch scheme and restore worktree")
    checkout_parser.add_argument("branch", metavar="方案名", help="scheme branch to check out")
    checkout_parser.set_defaults(func=cmd_checkout)

    status_parser = subparsers.add_parser("status", help="show staged, modified and untracked files")
    status_parser.add_argument("--short", action="store_true", help="compact status output")
    status_parser.set_defaults(func=cmd_status)

    diff_parser = subparsers.add_parser("diff", help="show line differences")
    diff_parser.add_argument("--stat", action="store_true", help="show insertion/deletion counts")
    diff_parser.add_argument("--cached", action="store_true", help="compare index with HEAD")
    diff_parser.add_argument("--head", action="store_true", help="compare worktree with HEAD")
    diff_parser.add_argument("refs", nargs="*", help="0/1/2 snapshot references")
    diff_parser.set_defaults(func=cmd_diff)

    reset_parser = subparsers.add_parser("reset", help="move current scheme to a snapshot")
    reset_group = reset_parser.add_mutually_exclusive_group()
    reset_group.add_argument("--soft", dest="mode", action="store_const", const="soft")
    reset_group.add_argument("--mixed", dest="mode", action="store_const", const="mixed")
    reset_parser.set_defaults(mode="mixed")
    reset_parser.add_argument("snapshot", help="target snapshot hash, hash prefix, or branch")
    reset_parser.set_defaults(func=cmd_reset)
    return parser


def main(argv: Sequence[str] | None = None, out=None, err=None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    parser = build_parser(err)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 2
        # argparse already rendered usage/error text to sys.stderr; mirror the
        # non-zero code without tearing down an embedded test runner.
        return code
    if not getattr(args, "func", None):
        parser.print_help(out)
        return 2
    try:
        return args.func(args, out)
    except CfgvaultError as exc:
        print(f"error: {exc}", file=err)
        return 1
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=err)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
