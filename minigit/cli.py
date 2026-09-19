"""Command-line interface and subcommand dispatch."""

import argparse
import sys

from . import commands
from .errors import MiniGitError

PROG = "minigit"


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG, description="A mini Git-like version control core.")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("init", help="create an empty repository")
    p.add_argument("path", nargs="?", default=None)
    p.set_defaults(func=commands.cmd_init)

    p = sub.add_parser("add", help="stage files into the index")
    p.add_argument("paths", nargs="+", metavar="<path>")
    p.set_defaults(func=commands.cmd_add)

    p = sub.add_parser("commit", help="record staged changes")
    p.add_argument("-m", "--message", required=True, metavar="<msg>")
    p.set_defaults(func=commands.cmd_commit)

    p = sub.add_parser("log", help="show commit history")
    p.add_argument("--oneline", action="store_true")
    p.set_defaults(func=commands.cmd_log)

    p = sub.add_parser("branch", help="list or create branches")
    p.add_argument("name", nargs="?", default=None)
    p.set_defaults(func=commands.cmd_branch)

    p = sub.add_parser("checkout", help="switch branches and restore the worktree")
    p.add_argument("branch", metavar="<branch>")
    p.set_defaults(func=commands.cmd_checkout)

    p = sub.add_parser("status", help="show staged/modified/untracked files")
    p.add_argument("--short", "-s", action="store_true")
    p.set_defaults(func=commands.cmd_status)

    p = sub.add_parser("diff", help="show changes between worktree/index/HEAD")
    p.add_argument("--cached", action="store_true", help="diff index against HEAD")
    p.add_argument("--stat", action="store_true", help="show per-file statistics")
    p.add_argument("commit", nargs="?", default=None,
                   help="diff the worktree against a commit")
    p.set_defaults(func=commands.cmd_diff)

    p = sub.add_parser("reset", help="move the current branch to a commit")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--soft", dest="mode", action="store_const",
                       const="soft", default="mixed")
    group.add_argument("--mixed", dest="mode", action="store_const", const="mixed")
    p.add_argument("commit", metavar="<commit>")
    p.set_defaults(func=commands.cmd_reset)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help(sys.stderr)
        return 2
    try:
        return args.func(args)
    except MiniGitError as exc:
        print(exc.message, file=sys.stderr)
        return exc.exit_code
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
