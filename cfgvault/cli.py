"""Command-line parsing and dispatch for cfgvault."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional, Sequence

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
from .errors import CfgvaultError, InvalidArgumentError, NotARepositoryError


class _NoExitParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InvalidArgumentError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _NoExitParser(prog="cfgvault", description="Snapshot and version promotion configurations")
    subparsers = parser.add_subparsers(dest="command", parser_class=_NoExitParser)

    init_parser = subparsers.add_parser("init", help="initialize a repository")
    init_parser.add_argument("path", nargs="?", default=None)

    add_parser = subparsers.add_parser("add", help="add file or directory contents to the index")
    add_parser.add_argument("paths", nargs="+")

    snap_parser = subparsers.add_parser("snap", help="create a snapshot from the index")
    snap_parser.add_argument("-m", "--message", required=True)

    log_parser = subparsers.add_parser("log", help="show snapshot history")
    log_parser.add_argument("--oneline", action="store_true")
    log_parser.add_argument("ref", nargs="?", default=None)

    branch_parser = subparsers.add_parser("branch", help="list or create a branch")
    branch_parser.add_argument("name", nargs="?", default=None)

    checkout_parser = subparsers.add_parser("checkout", help="switch branches and restore a tree")
    checkout_parser.add_argument("name")

    status_parser = subparsers.add_parser("status", help="show HEAD/index/worktree status")
    status_parser.add_argument("--short", action="store_true")

    diff_parser = subparsers.add_parser("diff", help="compare worktree, index, HEAD, or snapshots")
    diff_parser.add_argument("--cached", action="store_true")
    diff_parser.add_argument("--stat", action="store_true")
    diff_parser.add_argument("refs", nargs="*")

    reset_parser = subparsers.add_parser("reset", help="move current branch pointer")
    mode = reset_parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--soft", action="store_const", const="soft", dest="mode")
    mode.add_argument("--mixed", action="store_const", const="mixed", dest="mode")
    reset_parser.add_argument("snapshot")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])
        if not args.command:
            parser.print_help()
            return 2
        if args.command == "init":
            output = cmd_init(args.path)
        elif args.command == "add":
            output = cmd_add(args.paths)
        elif args.command == "snap":
            output = cmd_snap(args.message)
        elif args.command == "log":
            output = cmd_log(args.oneline, args.ref)
        elif args.command == "branch":
            output = cmd_branch(args.name)
        elif args.command == "checkout":
            output = cmd_checkout(args.name)
        elif args.command == "status":
            output = cmd_status(args.short)
        elif args.command == "diff":
            output = cmd_diff(args.cached, args.stat, args.refs)
        elif args.command == "reset":
            output = cmd_reset(args.mode, args.snapshot)
        else:  # pragma: no cover - argparse prevents reaching this branch
            raise CfgvaultError(f"unknown command: {args.command}")
    except NotARepositoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 128
    except CfgvaultError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: cfgvault: {exc.strerror or exc}", file=sys.stderr)
        return 1

    if output:
        print(output)
    return 0
