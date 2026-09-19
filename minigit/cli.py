"""Command-line parsing and dispatch for minigit."""

from __future__ import annotations

import sys
from typing import Sequence

from . import commands
from .errors import MinigitError, UsageError


def build_parser(argv: Sequence[str]) -> tuple[str, list[str]]:
    args = list(argv)
    if not args:
        raise UsageError(usage_text())
    command = args.pop(0)
    if command in ("-h", "--help", "help"):
        print(usage_text())
        raise SystemExit(0)
    if command not in {
        "init",
        "add",
        "commit",
        "log",
        "branch",
        "checkout",
        "status",
        "diff",
        "reset",
    }:
        raise UsageError(f"unknown command: {command}\n\n{usage_text()}")
    return command, args


def usage_text() -> str:
    return """usage: minigit <command> [arguments]

Commands:
  init [path]
  add <path>...
  commit -m <message> [--allow-empty]
  log [--oneline] [<commit>]
  branch [<name>]
  checkout <branch>
  status [--short]
  diff [--cached] [--stat] [<commit>]
  reset (--soft|--mixed) <commit>
"""


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        command, rest = build_parser(args)
        if command == "init":
            if len(rest) > 1:
                raise UsageError("init accepts at most one path")
            return commands.cmd_init(rest[0] if rest else None)

        if command == "add":
            return commands.cmd_add(rest)

        if command == "commit":
            message = None
            allow_empty = False
            paths: list[str] = []
            index = 0
            while index < len(rest):
                arg = rest[index]
                if arg == "-m" or arg == "--message":
                    if index + 1 >= len(rest):
                        raise UsageError("commit requires a message after -m")
                    message = rest[index + 1]
                    index += 2
                elif arg.startswith("--message="):
                    message = arg.split("=", 1)[1]
                    index += 1
                elif arg == "--allow-empty":
                    allow_empty = True
                    index += 1
                else:
                    raise UsageError(f"unknown commit argument: {arg}")
            return commands.cmd_commit(message, allow_empty=allow_empty)

        if command == "log":
            oneline = False
            revision = None
            for arg in rest:
                if arg == "--oneline":
                    oneline = True
                elif arg.startswith("-") and arg != "-":
                    raise UsageError(f"unknown log option: {arg}")
                elif revision is None:
                    revision = arg
                else:
                    raise UsageError("log accepts at most one commit reference")
            return commands.cmd_log(oneline=oneline, revision=revision)

        if command == "branch":
            if len(rest) > 1:
                raise UsageError("branch accepts at most one name")
            return commands.cmd_branch(rest[0] if rest else None)

        if command == "checkout":
            if len(rest) != 1:
                raise UsageError("checkout requires exactly one branch name")
            return commands.cmd_checkout(rest[0])

        if command == "status":
            if any(arg not in ("--short", "-s") for arg in rest):
                raise UsageError("status only supports --short")
            return commands.cmd_status(short=bool(rest))

        if command == "diff":
            cached = False
            stat = False
            revision = None
            for arg in rest:
                if arg in ("--cached", "--staged"):
                    cached = True
                elif arg == "--stat":
                    stat = True
                elif arg.startswith("-"):
                    raise UsageError(f"unknown diff option: {arg}")
                elif revision is None:
                    revision = arg
                else:
                    raise UsageError("diff accepts at most one revision")
            return commands.cmd_diff(cached=cached, stat=stat, revision=revision)

        if command == "reset":
            mode = None
            revision = None
            for arg in rest:
                if arg in ("--soft", "--mixed"):
                    mode = arg
                elif arg.startswith("-"):
                    raise UsageError(f"unknown reset option: {arg}")
                elif revision is None:
                    revision = arg
                else:
                    raise UsageError("reset accepts one commit reference")
            return commands.cmd_reset(mode, revision)

        raise AssertionError("unreachable command")
    except (MinigitError, OSError, ValueError) as exc:
        print(f"minigit: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
