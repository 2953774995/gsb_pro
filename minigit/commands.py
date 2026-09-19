"""minigit sub-command implementations.

Each ``cmd_*`` function receives the positional/flag arguments already
split by :mod:`minigit.cli` and returns a string (printed to stdout) or
``None``.  User errors raise :class:`~minigit.errors.MiniGitError`;
the CLI turns those into a clear stderr message plus a non-zero exit.
"""

import os
import time as _time

from . import diff as diff_mod
from . import objects as obj
from . import refs as refs_mod
from . import status as status_mod
from .errors import MiniGitError, RefNotFoundError, UsageError
from .ignore import IgnoreMatcher, walk_files
from .index import Index, load_index, save_index
from .repository import DEFAULT_BRANCH, Repository
from .worktree import hash_file, restore_tree

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# --------------------------------------------------------------------- helpers
def _identity():
    """Resolve author identity from env vars (git-compatible fallbacks)."""
    name = (
        os.environ.get("MINIGIT_AUTHOR_NAME")
        or os.environ.get("GIT_AUTHOR_NAME")
        or os.environ.get("GIT_COMMITTER_NAME")
        or "minigit"
    )
    email = (
        os.environ.get("MINIGIT_AUTHOR_EMAIL")
        or os.environ.get("GIT_AUTHOR_EMAIL")
        or os.environ.get("GIT_COMMITTER_EMAIL")
        or "minigit@example.com"
    )
    return name, email


def _timestamp():
    raw = (
        os.environ.get("MINIGIT_AUTHOR_DATE")
        or os.environ.get("GIT_AUTHOR_DATE")
        or os.environ.get("GIT_COMMITTER_DATE")
    )
    if raw:
        try:
            return int(raw.split()[0])
        except (ValueError, IndexError):
            pass
    return int(_time.time())


def _format_author(line):
    """``Name <email> 123 +0800`` -> ``(name, 'Date Time')`` display tuple."""
    lt = line.find("<")
    gt = line.find(">")
    name = line[:lt].strip()
    tail = line[gt + 1 :].split()
    ts, tz = int(tail[0]), tail[1]
    sign = 1 if tz[0] == "+" else -1
    offset = sign * (int(tz[1:3]) * 3600 + int(tz[3:5]) * 60)
    dt = _time.gmtime(ts + offset)
    date_str = "%s %d %02d:%02d:%02d %d" % (
        MONTHS[dt.tm_mon - 1], dt.tm_mday, dt.tm_hour, dt.tm_min, dt.tm_sec,
        dt.tm_year,
    )
    return name, date_str


def _read_work_bytes(repo, path):
    with open(os.path.join(repo.root, path), "rb") as fh:
        return fh.read()


def _read_blob_bytes(repo, path, entries, missing=None):
    entry = entries.get(path)
    if entry is None:
        return missing if missing is not None else b""
    return obj.read_blob(repo, entry[1])


# ========================================================================= init
def cmd_init(args):
    if args:
        raise UsageError("usage: minigit init")
    repo = Repository.init()
    return "Initialized empty minigit repository in %s" % repo.gitdir


# ========================================================================== add
def _paths_from_arg(repo, arg, matcher):
    """Resolve an add argument to ``[(relpath, abspath)]``."""
    if arg == ".":
        return walk_files(repo, matcher)
    abspath = os.path.abspath(arg)
    rel = repo.relpath(abspath)
    if not os.path.lexists(abspath):
        raise MiniGitError(
            "fatal: pathspec '%s' did not match any files" % arg
        )
    if os.path.isdir(abspath) and not os.path.islink(abspath):
        found = [(p, a) for p, a in walk_files(repo, matcher)
                 if p == rel or p.startswith(rel + "/")]
        if not found:
            return []
        return found
    if matcher.is_ignored(rel, is_dir=False):
        return []
    return [(rel, abspath)]


def cmd_add(args):
    if not args:
        raise UsageError("usage: minigit add <path>...")
    repo = Repository.find()
    matcher = IgnoreMatcher.for_repo(repo)
    idx = load_index(repo)

    for arg in args:
        if arg == ".":
            for path, abspath in walk_files(repo, matcher):
                if os.path.islink(abspath):
                    raise MiniGitError(
                        "fatal: symbolic links are not supported: %s" % path)
                mode, sha = hash_file(repo, abspath)
                idx.add(path, mode, sha)
            continue
        rel = repo.relpath(os.path.abspath(arg))
        # Staging a deletion: tracked path that no longer exists.
        abspath = os.path.join(repo.root, rel)
        if not os.path.lexists(abspath):
            if rel in idx:
                idx.remove(rel)
                save_index(repo, idx)
            else:
                raise MiniGitError(
                    "fatal: pathspec '%s' did not match any files" % arg
                )
            continue
        for path, abspath in _paths_from_arg(repo, arg, matcher):
            if os.path.islink(abspath):
                raise MiniGitError("fatal: symbolic links are not supported: %s"
                                   % path)
            mode, sha = hash_file(repo, abspath)
            idx.add(path, mode, sha)
    save_index(repo, idx)
    return None


# ======================================================================= commit
def _parse_message(args):
    """Extract the ``-m/--message`` message, rejecting stray arguments."""
    message = None
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-m", "--message"):
            if i + 1 >= len(args):
                raise UsageError("error: option %s requires a message" % a)
            message = args[i + 1]
            i += 2
        elif a.startswith("--message="):
            message = a.split("=", 1)[1]
            i += 1
        elif a == "--allow-empty":
            i += 1  # handled by caller; parsed here to be accepted
        else:
            raise UsageError("error: unknown commit argument: %s" % a)
    if message is None or not message.strip():
        raise UsageError("error: commit message required (use -m '...')")
    return message


def cmd_commit(args):
    allow_empty = "--allow-empty" in args
    message = _parse_message([a for a in args if a != "--allow-empty"])
    repo = Repository.find()
    idx = load_index(repo)
    parent = refs_mod.head_commit(repo)

    if parent is None:
        if len(idx) == 0 and not allow_empty:
            raise MiniGitError(
                "error: nothing to commit (empty index); "
                "use --allow-empty to create an empty initial commit"
            )
    else:
        parent_tree = obj.read_commit(repo, parent)["tree"]
        current_tree = obj.build_tree(repo, dict(idx.entries))
        if current_tree == parent_tree and not allow_empty:
            raise MiniGitError(
                "nothing to commit, working tree clean (no changes staged "
                "or already committed); use --allow-empty to force"
            )

    tree_sha = obj.build_tree(repo, dict(idx.entries))
    name, email = _identity()
    parents = [parent] if parent else []
    commit_sha = obj.write_commit(
        repo, tree_sha, parents, name, email, message, _timestamp()
    )
    branch = refs_mod.current_branch(repo)
    refs_mod.write_branch(repo, branch, commit_sha)
    short = commit_sha[:7]
    root_note = " (root-commit)" if not parents else ""
    return "[%s%s %s] %s" % (branch, root_note, short, message.splitlines()[0])


# ========================================================================== log
def cmd_log(args):
    oneline = False
    rest = []
    for a in args:
        if a == "--oneline":
            oneline = True
        elif a == "--":
            pass
        else:
            rest.append(a)
    repo = Repository.find()
    ref = rest[0] if rest else "HEAD"
    sha = refs_mod.resolve_commit(repo, ref)
    out = []
    seen = set()
    while sha and sha not in seen:
        seen.add(sha)
        commit = obj.read_commit(repo, sha)
        if oneline:
            out.append("%s %s" % (sha[:7], commit["message"].splitlines()[0]))
        else:
            author_name, date_str = _format_author(commit.get("author", ""))
            out.append("commit %s" % sha)
            out.append("Author: %s" % author_name)
            out.append("Date:   %s" % date_str)
            out.append("")
            for line in commit["message"].splitlines():
                out.append("    " + line)
            out.append("")
        if not commit["parents"]:
            break
        sha = commit["parents"][0]
    return "\n".join(out).rstrip("\n") + ("\n" if out else "")


# ======================================================================= branch
def cmd_branch(args):
    repo = Repository.find()
    if not args:
        current = refs_mod.current_branch(repo)
        lines = []
        for name, _sha in refs_mod.list_branches(repo):
            marker = "*" if name == current else " "
            lines.append("%s %s" % (marker, name))
        return "\n".join(lines) + ("\n" if lines else "")

    name = args[0]
    if len(args) > 1:
        raise UsageError("usage: minigit branch [<name>]")
    if refs_mod.branch_exists(repo, name):
        raise MiniGitError("fatal: a branch named '%s' already exists" % name)
    point = refs_mod.head_commit(repo)
    if point is None:
        raise MiniGitError(
            "fatal: not a valid object name: 'HEAD' "
            "(make at least one commit before creating a branch)"
        )
    refs_mod.validate_branch_name(name)
    refs_mod.write_branch(repo, name, point)
    return None


# ===================================================================== checkout
def cmd_checkout(args):
    if not args:
        raise UsageError("usage: minigit checkout <branch>")
    name = args[0]
    repo = Repository.find()
    if not refs_mod.branch_exists(repo, name):
        raise RefNotFoundError(
            "error: pathspec '%s' did not match any branch(s) known to minigit"
            % name
        )
    current = refs_mod.current_branch(repo)
    if name == current:
        return "Already on '%s'" % name

    target_commit_sha = refs_mod.read_branch(repo, name)
    target_commit = obj.read_commit(repo, target_commit_sha)
    target_entries = obj.flatten_tree(repo, target_commit["tree"])

    idx = load_index(repo)
    restore_tree(repo, target_entries, idx.paths())
    # Reset the index to the checked-out tree, then point HEAD at the branch.
    new_index = Index({p: tuple(v) for p, v in target_entries.items()})
    save_index(repo, new_index)
    refs_mod.write_head_symbolic(repo, name)
    return "Switched to branch '%s'" % name


# ======================================================================= status
def cmd_status(args):
    short = False
    for a in args:
        if a in ("-s", "--short"):
            short = True
        else:
            raise UsageError("usage: minigit status [--short]")
    repo = Repository.find()
    st = status_mod.compute_status(repo)

    if short:
        codes = status_mod.short_codes(st)
        return "".join("%s %s\n" % (code, path)
                       for path, code in sorted(codes.items()))

    lines = ["On branch %s" % refs_mod.current_branch(repo)]
    staged = st["staged"]
    worktree = st["worktree"]
    untracked = st["untracked"]

    if staged:
        lines.append("Changes to be committed:")
        lines.append('  (use "minigit reset HEAD <file>..." to unstage)')
        lines.append("")
        for path, (code, ie, he) in sorted(staged.items()):
            label = {"A": "new file:  ", "M": "modified:  ", "D": "deleted:   "}[code]
            lines.append("\t%s%s" % (label, path))
        lines.append("")
    if worktree:
        lines.append("Changes not staged for commit:")
        lines.append('  (use "minigit add <file>..." to update what will be committed)')
        lines.append("")
        for path, (code, wt, ie) in sorted(worktree.items()):
            label = "modified:  " if code == "M" else "deleted:   "
            lines.append("\t%s%s" % (label, path))
        lines.append("")
    if untracked:
        lines.append("Untracked files:")
        lines.append("")
        for path in sorted(untracked):
            lines.append("\t%s" % path)
        lines.append("")
    if not staged and not worktree and not untracked:
        lines.append("nothing to commit, working tree clean")
    return "\n".join(lines) + "\n"


# ========================================================================= diff
def _parse_diff_flags(args):
    cached = False
    stat = False
    refs = []
    for a in args:
        if a in ("--cached", "--staged"):
            cached = True
        elif a == "--stat":
            stat = True
        elif a.startswith("-"):
            raise UsageError("error: unknown diff option: %s" % a)
        else:
            refs.append(a)
    if len(refs) > 1:
        raise UsageError("usage: minigit diff [--cached] [--stat] [<commit>]")
    return cached, stat, refs[0] if refs else None


def cmd_diff(args):
    cached, stat, ref = _parse_diff_flags(args)
    repo = Repository.find()
    idx = load_index(repo)

    if cached:
        # HEAD tree  vs  index.
        head_entries = refs_mod.head_tree_entries(repo)
        old_files = head_entries
        new_files = dict(idx.entries)

        def read_old(path):
            return _read_blob_bytes(repo, path, head_entries)

        def read_new(path):
            return _read_blob_bytes(repo, path, dict(idx.entries))
    else:
        # index  vs  working tree (or given commit  vs  working tree).
        if ref is not None:
            base_sha = refs_mod.resolve_commit(repo, ref)
            base_entries = obj.flatten_tree(
                repo, obj.read_commit(repo, base_sha)["tree"]
            )
        else:
            base_entries = dict(idx.entries)
        matcher = IgnoreMatcher.for_repo(repo)
        on_disk = dict(walk_files(repo, matcher))
        old_files = base_entries
        new_files = {}
        for path in base_entries:
            abspath = on_disk.get(path, os.path.join(repo.root, path))
            if os.path.isfile(abspath):
                _wt_mode, wt_sha = hash_file(repo, abspath)
                new_files[path] = wt_sha
            else:
                new_files[path] = None  # tracked file deleted from disk

        def read_old(path):
            return _read_blob_bytes(repo, path, base_entries)

        def read_new(path):
            abspath = on_disk.get(path, os.path.join(repo.root, path))
            if not os.path.isfile(abspath):
                return b""
            return _read_work_bytes(repo, path)

    return diff_mod.diff_entries(
        old_files, new_files, read_old=read_old, read_new=read_new, stat=stat
    )


# ======================================================================== reset
def cmd_reset(args):
    mode = "mixed"
    ref = None
    for a in args:
        if a == "--soft":
            mode = "soft"
        elif a == "--mixed":
            mode = "mixed"
        elif a.startswith("-"):
            raise UsageError("error: unknown reset option: %s" % a)
        elif ref is None:
            ref = a
        else:
            raise UsageError("usage: minigit reset [--soft|--mixed] <commit>")
    if ref is None:
        raise UsageError("usage: minigit reset [--soft|--mixed] <commit>")

    repo = Repository.find()
    target = refs_mod.resolve_commit(repo, ref)  # raises on invalid reference
    branch = refs_mod.current_branch(repo)
    refs_mod.write_branch(repo, branch, target)  # move branch pointer

    if mode == "mixed":
        tree_entries = obj.flatten_tree(repo, obj.read_commit(repo, target)["tree"])
        save_index(repo, Index({p: tuple(v) for p, v in tree_entries.items()}))
        return "Unstaged changes after reset to %s" % target[:7]
    return None
