"""Command-line entry point and sub-command dispatch.

Usage::

    python -m minigit <command> [arguments...]

Exit code is 0 on success and 1 on any user-facing error.
"""

import sys

from . import commands
from .errors import MiniGitError, UsageError
from .repository import Repository

COMMANDS = (
    "init", "add", "commit", "log", "branch", "checkout",
    "status", "diff", "reset",
)

USAGE = """\
usage: minigit <command> [<args>]

Core commands:
  init                  Create an empty minigit repository (.minigit/)
  add <path>...         Stage files (or stage a deletion of a tracked path)
  commit -m <msg>       Record the index as a commit on the current branch
  log [--oneline]       Show commit history along the first-parent chain
  branch [<name>]       List branches (* marks current) or create one
  checkout <branch>     Switch branches and restore the working tree
  status [--short]      Show staged / modified / deleted / untracked files
  diff [--cached] [--stat] [<commit>]
                        Show changes (default: worktree vs index)
  reset --soft <commit> Move the current branch (index/worktree untouched)
  reset --mixed <commit> Move the branch and reset the index (default)
"""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        sys.stdout.write(USAGE)
        return 0
    command, rest = argv[0], argv[1:]

    if command not in COMMANDS:
        # 'init' is the only command usable outside a repository, so check
        # the typo before attempting repository discovery.
        sys.stderr.write(
            "minigit: '%s' is not a minigit command. See 'minigit --help'.\n"
            % command
        )
        return 1

    handler = getattr(commands, "cmd_" + command)
    try:
        if command != "init":
            Repository.find()  # surface a clear "not a repository" error
        output = handler(rest)
    except UsageError as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1
    except MiniGitError as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1
    except FileNotFoundError as exc:
        sys.stderr.write("fatal: %s\n" % exc)
        return 1
    except IsADirectoryError as exc:
        sys.stderr.write("fatal: %s\n" % exc)
        return 1

    if output:
        sys.stdout.write(output if output.endswith("\n") else output + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
