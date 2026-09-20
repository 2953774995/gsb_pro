"""Command-line parsing and dispatch for minigit."""

import argparse
import sys

from . import commands
from .errors import MiniGitError


def build_parser():
    parser = argparse.ArgumentParser(
        prog="minigit",
        description="A mini Git-like version control system (stdlib only).")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("init", help="create a new repository")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=commands.cmd_init)

    p = sub.add_parser("add", help="stage files into the index")
    p.add_argument("paths", nargs="+", metavar="<path>")
    p.set_defaults(func=commands.cmd_add)

    p = sub.add_parser("commit", help="record staged changes")
    p.add_argument("-m", "--message", required=True, help="commit message")
    p.set_defaults(func=commands.cmd_commit)

    p = sub.add_parser("log", help="show commit history")
    p.add_argument("--oneline", action="store_true",
                   help="short hash plus first message line")
    p.set_defaults(func=commands.cmd_log)

    p = sub.add_parser("status", help="show working tree status")
    p.add_argument("--short", "-s", action="store_true",
                   help="compact XY-style output")
    p.set_defaults(func=commands.cmd_status)

    p = sub.add_parser("diff", help="show changes (default: workdir vs index)")
    p.add_argument("--cached", action="store_true",
                   help="diff index against HEAD")
    p.add_argument("--stat", action="store_true",
                   help="per-file added/deleted line counts")
    p.set_defaults(func=commands.cmd_diff)

    p = sub.add_parser("branch", help="list or create branches")
    p.add_argument("name", nargs="?", help="new branch name (omit to list)")
    p.set_defaults(func=commands.cmd_branch)

    p = sub.add_parser("checkout", help="switch to a branch")
    p.add_argument("branch", help="branch to switch to")
    p.set_defaults(func=commands.cmd_checkout)

    p = sub.add_parser("reset", help="move the current branch to a commit")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--soft", action="store_true",
                      help="move the branch pointer only")
    mode.add_argument("--mixed", action="store_true",
                      help="also reset the index (default)")
    p.add_argument("commit", help="branch name, HEAD, or commit sha")
    p.set_defaults(func=commands.cmd_reset)

    return parser


def main(argv=None):
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse errors: message already on stderr
        return int(exc.code or 0)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    try:
        return int(args.func(args) or 0)
    except MiniGitError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
