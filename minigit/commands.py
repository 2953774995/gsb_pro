"""Implementations of the minigit subcommands."""

import os
import time

from . import diff as diffmod
from . import index as indexmod
from . import objects
from . import refs
from .errors import MiniGitError
from .ignore import IgnoreRules
from .repo import MINIGIT_DIR, find_repo, init_repo


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _author():
    name = os.environ.get("MINIGIT_AUTHOR_NAME", "MiniGit User")
    email = os.environ.get("MINIGIT_AUTHOR_EMAIL", "minigit@example.com")
    return "%s <%s>" % (name, email)


def _now():
    epoch = int(os.environ.get("MINIGIT_COMMIT_DATE", time.time()))
    tz = time.strftime("%z", time.localtime(epoch)) or "+0000"
    return epoch, tz


def _format_date(epoch, tz):
    return time.strftime("%a %b %d %H:%M:%S %Y", time.localtime(epoch)) + " " + tz


def _file_mode(path):
    if os.stat(path).st_mode & 0o111:
        return objects.MODE_EXEC
    return objects.MODE_FILE


def _read_work_file(repo, relpath):
    with open(os.path.join(repo.root, relpath), "rb") as fh:
        return fh.read()


def _hash_work_file(repo, relpath):
    return objects.hash_object(objects.BLOB, _read_work_file(repo, relpath))


def _walk_worktree(repo, rules):
    """Yield repo-relative paths of candidate files (skips .minigit/ignored)."""
    for dirpath, dirnames, filenames in os.walk(repo.root):
        rel_dir = os.path.relpath(dirpath, repo.root)
        kept = []
        for d in sorted(dirnames):
            rel = d if rel_dir == "." else rel_dir + "/" + d
            if d == MINIGIT_DIR or rules.matches(rel, is_dir=True):
                continue
            kept.append(d)
        dirnames[:] = kept
        for f in sorted(filenames):
            rel = f if rel_dir == "." else rel_dir + "/" + f
            if rules.matches(rel, is_dir=False):
                continue
            yield rel


def _parse_commit(data):
    """Split a commit payload into (headers_dict, message)."""
    text = data.decode("utf-8")
    head, _, message = text.partition("\n\n")
    headers = {}
    parents = []
    for line in head.splitlines():
        key, _, value = line.partition(" ")
        if key == "parent":
            parents.append(value)
        else:
            headers[key] = value
    headers["parents"] = parents
    return headers, message


def _head_tree_entries(repo):
    """Flattened {path: (mode, oid)} of the HEAD commit's tree (or {})."""
    head = refs.head_commit(repo)
    if head is None:
        return {}
    _, data = objects.read_object(repo, head)
    headers, _ = _parse_commit(data)
    return objects.flatten_tree(repo, headers["tree"])


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def cmd_init(args):
    repo, created = init_repo(args.path)
    if created:
        print("Initialized empty minigit repository in %s" % repo.git_dir)
    else:
        print("Reinitialized existing minigit repository in %s" % repo.git_dir)
    return 0


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

def cmd_add(args):
    repo = find_repo()
    rules = IgnoreRules.from_repo(repo)
    entries = indexmod.read_index(repo)
    added = []
    for target in args.paths:
        apath = os.path.abspath(target)
        rel = repo.relpath(apath)
        if rel is None:
            raise MiniGitError("fatal: %s: outside repository" % target)
        if rel == "":
            rel = "."
        full = os.path.join(repo.root, rel)
        if os.path.isfile(full):
            _stage_file(repo, entries, rel, rules, added)
        elif os.path.isdir(full):
            prefix = "" if rel == "." else rel.rstrip("/") + "/"
            for path in _walk_worktree(repo, rules):
                if path.startswith(prefix):
                    _stage_file(repo, entries, path, rules, added)
        else:
            raise MiniGitError("fatal: pathspec '%s' did not match any files" % target)
    indexmod.write_index(repo, entries)
    for path in added:
        print("add %s" % path)
    return 0


def _stage_file(repo, entries, relpath, rules, added):
    relpath = relpath.replace(os.sep, "/")
    if relpath.split("/")[0] == MINIGIT_DIR or rules.matches(relpath):
        return
    full = os.path.join(repo.root, relpath)
    with open(full, "rb") as fh:
        data = fh.read()
    oid = objects.write_object(repo, objects.BLOB, data)
    mode = _file_mode(full)
    old = entries.get(relpath)
    if old is None or old.oid != oid or old.mode != mode:
        entries[relpath] = indexmod.IndexEntry(mode, oid, relpath)
        added.append(relpath)


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------

def cmd_commit(args):
    repo = find_repo()
    entries = indexmod.read_index(repo)
    if not entries:
        raise MiniGitError("nothing to commit (staging area is empty)")
    tree_oid = indexmod.build_tree(repo, entries)
    parent = refs.head_commit(repo)
    if parent is not None:
        _, pdata = objects.read_object(repo, parent)
        pheaders, _ = _parse_commit(pdata)
        if pheaders["tree"] == tree_oid:
            # Project convention: empty commits are rejected, consistently.
            raise MiniGitError("nothing to commit (no changes staged since last commit)")
    epoch, tz = _now()
    lines = ["tree %s" % tree_oid]
    if parent is not None:
        lines.append("parent %s" % parent)
    lines.append("author %s %d %s" % (_author(), epoch, tz))
    lines.append("committer %s %d %s" % (_author(), epoch, tz))
    payload = "\n".join(lines) + "\n\n" + args.message + "\n"
    commit_oid = objects.write_object(repo, objects.COMMIT, payload.encode("utf-8"))
    refs.update_head_ref(repo, commit_oid)
    branch = refs.current_branch(repo) or "detached HEAD"
    root = " (root-commit)" if parent is None else ""
    first_line = args.message.splitlines()[0] if args.message else ""
    print("[%s%s %s] %s" % (branch, root, commit_oid[:7], first_line))
    return 0


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------

def cmd_log(args):
    repo = find_repo()
    oid = refs.head_commit(repo)
    if oid is None:
        raise MiniGitError("fatal: your current branch does not have any commits yet")
    first = True
    while oid is not None:
        _, data = objects.read_object(repo, oid)
        headers, message = _parse_commit(data)
        if args.oneline:
            summary = message.splitlines()[0] if message.strip() else ""
            print("%s %s" % (oid[:7], summary))
        else:
            if not first:
                print("")
            print("commit %s" % oid)
            print("Author: %s" % headers.get("author", "unknown").rsplit(" ", 2)[0])
            parts = headers.get("author", "").rsplit(" ", 2)
            if len(parts) == 3:
                print("Date:   %s" % _format_date(int(parts[1]), parts[2]))
            print("")
            for line in message.rstrip("\n").splitlines():
                print("    " + line)
        first = False
        oid = headers["parents"][0] if headers["parents"] else None
    return 0


# ---------------------------------------------------------------------------
# branch
# ---------------------------------------------------------------------------

def cmd_branch(args):
    repo = find_repo()
    if args.name is None:
        current = refs.current_branch(repo)
        for name in refs.list_branches(repo):
            marker = "* " if name == current else "  "
            print("%s%s" % (marker, name))
        return 0
    if refs.branch_exists(repo, args.name):
        raise MiniGitError("fatal: a branch named '%s' already exists" % args.name)
    head = refs.head_commit(repo)
    if head is None:
        raise MiniGitError("fatal: not a valid object name: HEAD (no commits yet)")
    refs.create_branch(repo, args.name, head)
    print("created branch '%s' at %s" % (args.name, head[:7]))
    return 0


# ---------------------------------------------------------------------------
# checkout
# ---------------------------------------------------------------------------

def cmd_checkout(args):
    repo = find_repo()
    if not refs.branch_exists(repo, args.branch):
        raise MiniGitError("error: pathspec '%s' did not match any known branch" % args.branch)
    target_oid = refs.read_branch(repo, args.branch)
    _, data = objects.read_object(repo, target_oid)
    headers, _ = _parse_commit(data)
    target = objects.flatten_tree(repo, headers["tree"])

    entries = indexmod.read_index(repo)
    tracked = set(entries)

    # Remove tracked files that do not exist in the target commit.
    for path in sorted(tracked - set(target)):
        full = os.path.join(repo.root, path)
        if os.path.exists(full):
            os.remove(full)
        _prune_empty_dirs(repo, os.path.dirname(full))

    # Restore every file of the target commit.
    for path in sorted(target):
        mode, oid = target[path]
        _, blob = objects.read_object(repo, oid)
        full = os.path.join(repo.root, path)
        os.makedirs(os.path.dirname(full) or repo.root, exist_ok=True)
        if os.path.exists(full):
            with open(full, "rb") as fh:
                if fh.read() == blob:
                    continue
        with open(full, "wb") as fh:
            fh.write(blob)

    # Point the index and HEAD at the target commit.
    new_entries = {
        path: indexmod.IndexEntry(mode, oid, path)
        for path, (mode, oid) in target.items()
    }
    indexmod.write_index(repo, new_entries)
    refs.set_head_branch(repo, args.branch)
    print("Switched to branch '%s'" % args.branch)
    return 0


def _prune_empty_dirs(repo, dirpath):
    while dirpath and os.path.abspath(dirpath) != repo.root:
        if os.path.isdir(dirpath) and not os.listdir(dirpath):
            os.rmdir(dirpath)
            dirpath = os.path.dirname(dirpath)
        else:
            break


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def _compute_status(repo):
    """Return (staged, unstaged, untracked) change dictionaries/lists."""
    rules = IgnoreRules.from_repo(repo)
    entries = indexmod.read_index(repo)
    head = _head_tree_entries(repo)

    staged = {}   # path -> "new file" | "modified" | "deleted"
    for path, entry in entries.items():
        if path not in head:
            staged[path] = "new file"
        elif head[path] != (entry.mode, entry.oid):
            staged[path] = "modified"
    for path in head:
        if path not in entries:
            staged[path] = "deleted"

    unstaged = {}  # path -> "modified" | "deleted"
    for path, entry in entries.items():
        full = os.path.join(repo.root, path)
        if not os.path.exists(full):
            unstaged[path] = "deleted"
        elif _file_mode(full) != entry.mode or _hash_work_file(repo, path) != entry.oid:
            unstaged[path] = "modified"

    untracked = []
    for path in _walk_worktree(repo, rules):
        if path not in entries:
            untracked.append(path)
    return staged, unstaged, untracked


def cmd_status(args):
    repo = find_repo()
    staged, unstaged, untracked = _compute_status(repo)
    if args.short:
        for path in sorted(staged):
            code = {"new file": "A ", "modified": "M ", "deleted": "D "}[staged[path]]
            print("%s %s" % (code, path))
        for path in sorted(unstaged):
            code = " M" if unstaged[path] == "modified" else " D"
            if path in staged:
                continue  # already reported in the staged column
            print("%s %s" % (code, path))
        for path in untracked:
            print("?? %s" % path)
        return 0

    branch = refs.current_branch(repo)
    print("On branch %s" % (branch or "HEAD (detached)"))
    if refs.head_commit(repo) is None:
        print("\nNo commits yet")
    if staged:
        print("\nChanges to be committed:")
        for path in sorted(staged):
            print("  %s:   %s" % (staged[path], path))
    if unstaged:
        print("\nChanges not staged for commit:")
        for path in sorted(unstaged):
            print("  %s:   %s" % (unstaged[path], path))
    if untracked:
        print("\nUntracked files:")
        for path in untracked:
            print("  %s" % path)
    if not staged and not unstaged and not untracked:
        print("\nnothing to commit, working tree clean")
    return 0


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------

def _blob_data(repo, oid):
    if oid is None:
        return b""
    _, data = objects.read_object(repo, oid)
    return data


def cmd_diff(args):
    repo = find_repo()
    entries = indexmod.read_index(repo)
    paths = set()
    pairs = []  # (path, old_bytes, new_bytes)

    if args.cached:
        head = _head_tree_entries(repo)
        for path in sorted(set(head) | set(entries)):
            old = head.get(path, (None, None))[1]
            new = entries[path].oid if path in entries else None
            if old != new:
                pairs.append((path, _blob_data(repo, old), _blob_data(repo, new)))
    elif args.commit is not None:
        commit = refs.resolve_revision(repo, args.commit)
        _, data = objects.read_object(repo, commit)
        headers, _ = _parse_commit(data)
        base = objects.flatten_tree(repo, headers["tree"])
        work = {p: None for p in _walk_worktree(repo, IgnoreRules.from_repo(repo))}
        for path in sorted(set(base) | set(work) | set(entries)):
            old = base.get(path, (None, None))[1]
            full = os.path.join(repo.root, path)
            new_data = _read_work_file(repo, path) if os.path.isfile(full) else None
            old_data = _blob_data(repo, old)
            if new_data is None:
                if old is not None:
                    pairs.append((path, old_data, b""))
            elif old_data != new_data:
                pairs.append((path, old_data, new_data))
    else:
        for path in sorted(entries):
            entry = entries[path]
            full = os.path.join(repo.root, path)
            old_data = _blob_data(repo, entry.oid)
            if not os.path.exists(full):
                pairs.append((path, old_data, b""))
                continue
            new_data = _read_work_file(repo, path)
            if new_data != old_data:
                pairs.append((path, old_data, new_data))

    if args.stat:
        total_add = total_del = 0
        for path, old_data, new_data in pairs:
            added, deleted = diffmod.count_changes(old_data, new_data)
            total_add += added
            total_del += deleted
            print(" %s | +%d -%d" % (path, added, deleted))
        if pairs:
            print(" %d file(s) changed, %d insertions(+), %d deletions(-)"
                  % (len(pairs), total_add, total_del))
        return 0

    for path, old_data, new_data in pairs:
        print("diff --minigit a/%s b/%s" % (path, path))
        old_label = "a/" + path if old_data else "/dev/null"
        new_label = "b/" + path if new_data else "/dev/null"
        out = diffmod.unified_diff(old_data, new_data, old_label, new_label)
        print(out, end="")
    return 0


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------

def cmd_reset(args):
    repo = find_repo()
    commit = refs.resolve_revision(repo, args.commit)
    refs.update_head_ref(repo, commit)
    if args.mode == "mixed":
        _, data = objects.read_object(repo, commit)
        headers, _ = _parse_commit(data)
        flat = objects.flatten_tree(repo, headers["tree"])
        entries = {
            path: indexmod.IndexEntry(mode, oid, path)
            for path, (mode, oid) in flat.items()
        }
        indexmod.write_index(repo, entries)
        print("Unstaged changes after reset:")
    else:
        print("HEAD is now at %s" % commit[:7])
    return 0
