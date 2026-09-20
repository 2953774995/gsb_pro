"""Subcommand implementations. Each returns a process-style exit code."""

import os
import time

from . import diffutil
from .errors import MiniGitError
from .objects import (
    COMMIT, build_tree, encode_commit, flatten_tree, hash_object, parse_commit,
    parse_identity,
)
from .repository import MINIGIT_DIR, find_repo, init_repo
from .workspace import checkout_commit, head_tree_entries, iter_workdir_files


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _tz_offset():
    offset = getattr(time.localtime(), "tm_gmtoff", None) or 0
    sign = "+" if offset >= 0 else "-"
    offset = abs(offset)
    return "%s%02d%02d" % (sign, offset // 3600, (offset % 3600) // 60)


def _identity():
    name = os.environ.get("MINIGIT_AUTHOR_NAME", "minigit")
    email = os.environ.get("MINIGIT_AUTHOR_EMAIL", "minigit@example.com")
    return "%s <%s> %d %s" % (name, email, int(time.time()), _tz_offset())


def _format_date(ts, tz):
    return time.strftime("%a %b %d %H:%M:%S %Y", time.localtime(ts)) + " " + tz


def _read_blob_text(repo, sha):
    _obj_type, data = repo.objects.read_object(sha)
    return data.decode("utf-8", errors="replace")


def _read_file_text(path):
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", errors="replace")


def resolve_commit(repo, name):
    """Resolve a branch name, HEAD, or (abbreviated) sha1 to a commit sha."""
    if name == "HEAD":
        head = repo.refs.head_commit()
        if head:
            return head
        raise MiniGitError("HEAD does not point at any commit yet")
    if repo.refs.branch_exists(name):
        return repo.refs.read_branch(name)
    if 4 <= len(name) <= 40 and all(c in "0123456789abcdef" for c in name.lower()):
        name = name.lower()
        matches = []
        if len(name) == 40:
            if repo.objects.has_object(name):
                matches = [name]
        else:
            subdir = os.path.join(repo.objects.objects_dir, name[:2])
            if os.path.isdir(subdir):
                matches = sorted(
                    name[:2] + f for f in os.listdir(subdir)
                    if (name[:2] + f).startswith(name) and not f.endswith(".tmp"))
        if len(matches) > 1:
            raise MiniGitError("ambiguous commit reference: %s" % name)
        if len(matches) == 1:
            obj_type, _data = repo.objects.read_object(matches[0])
            if obj_type != COMMIT:
                raise MiniGitError(
                    "object %s is a %s, not a commit" % (name, obj_type))
            return matches[0]
    raise MiniGitError("invalid commit reference: %s" % name)


def _walk_files(repo, directory):
    """Repo-relative files under ``directory`` (skips .minigit and ignored)."""
    result = []
    for root, dirs, files in os.walk(directory):
        rel_root = os.path.relpath(root, repo.workdir).replace(os.sep, "/")
        kept = []
        for d in sorted(dirs):
            if d == MINIGIT_DIR:
                continue
            rel = d if rel_root == "." else rel_root + "/" + d
            if not repo.ignore.is_ignored(rel, is_dir=True):
                kept.append(d)
        dirs[:] = kept
        for name in sorted(files):
            rel = name if rel_root == "." else rel_root + "/" + name
            result.append(rel)
    return result


def compute_status(repo):
    """Return (staged, unstaged, untracked).

    staged:   [(kind, path)] kind in {"new file", "modified", "deleted"}
    unstaged: [(kind, path)] kind in {"modified", "deleted"}
    untracked: [path]
    """
    head_map = head_tree_entries(repo)
    index = repo.index.entries

    staged = []
    for path in sorted(set(head_map) | set(index)):
        in_head, in_index = path in head_map, path in index
        if in_head and not in_index:
            staged.append(("deleted", path))
        elif in_index and not in_head:
            staged.append(("new file", path))
        elif head_map[path] != index[path]:
            staged.append(("modified", path))

    unstaged = []
    for path in sorted(index):
        fpath = repo.abspath(path)
        if not os.path.isfile(fpath):
            unstaged.append(("deleted", path))
            continue
        with open(fpath, "rb") as fh:
            if hash_object("blob", fh.read()) != index[path][1]:
                unstaged.append(("modified", path))

    untracked = [p for p in iter_workdir_files(repo) if p not in index]
    return staged, unstaged, untracked


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_init(args):
    gitdir = init_repo(args.path or ".")
    print("Initialized empty minigit repository in %s" % gitdir)
    return 0


def cmd_add(args):
    repo = find_repo()
    files = set()
    sync_dirs = []
    for raw in args.paths:
        abspath = os.path.abspath(raw)
        rel = os.path.relpath(abspath, repo.workdir).replace(os.sep, "/")
        if rel == ".." or rel.startswith("../"):
            raise MiniGitError("'%s' is outside the repository" % raw)
        if os.path.isfile(abspath):
            files.add(rel)
        elif os.path.isdir(abspath):
            sync_dirs.append(rel)
            files.update(_walk_files(repo, abspath))
        elif rel in repo.index.entries:
            repo.index.remove(rel)  # 'add' of a deleted tracked file
        else:
            raise MiniGitError("pathspec '%s' did not match any files" % raw)

    # Adding a directory also records deletions of tracked files below it.
    for d in sync_dirs:
        prefix = "" if d == "." else d + "/"
        for path in list(repo.index.entries):
            if prefix == "" or path == d or path.startswith(prefix):
                if not os.path.isfile(repo.abspath(path)):
                    repo.index.remove(path)

    for rel in sorted(files):
        if rel == MINIGIT_DIR or rel.startswith(MINIGIT_DIR + "/"):
            continue
        if repo.ignore.is_ignored(rel):
            continue
        full = repo.abspath(rel)
        if not os.path.isfile(full):
            continue
        with open(full, "rb") as fh:
            content = fh.read()
        sha = repo.objects.write_object("blob", content)
        mode = "100755" if os.access(full, os.X_OK) else "100644"
        repo.index.add(rel, mode, sha)
    repo.index.save()
    return 0


def cmd_commit(args):
    repo = find_repo()
    tree_sha = build_tree(repo.objects, repo.index.entries)
    head = repo.refs.head_commit()
    if head:
        parent_commit = parse_commit(repo.objects.read_object(head)[1])
        if parent_commit["tree"] == tree_sha:
            # Convention: a commit with no staged changes is rejected.
            print("nothing to commit, working tree clean")
            return 1
    elif not repo.index.entries:
        print("nothing to commit (empty index)")
        return 1

    author = _identity()
    parents = [head] if head else []
    data = encode_commit(tree_sha, parents, author, author, args.message)
    sha = repo.objects.write_object(COMMIT, data)
    repo.refs.update_head(sha)
    branch = repo.refs.current_branch() or "HEAD (detached)"
    first_line = args.message.splitlines()[0] if args.message.strip() else ""
    suffix = " (root-commit)" if not parents else ""
    print("[%s%s %s] %s" % (branch, suffix, sha[:7], first_line))
    return 0


def cmd_log(args):
    repo = find_repo()
    sha = repo.refs.head_commit()
    if not sha:
        branch = repo.refs.current_branch() or "HEAD"
        raise MiniGitError(
            "your current branch '%s' does not have any commits yet" % branch)
    while sha:
        obj_type, data = repo.objects.read_object(sha)
        if obj_type != COMMIT:
            raise MiniGitError("object %s is not a commit" % sha)
        commit = parse_commit(data)
        message = commit["message"]
        if args.oneline:
            first = message.strip().splitlines()[0] if message.strip() else ""
            print("%s %s" % (sha[:7], first))
        else:
            name, email, ts, tz = parse_identity(commit["author"])
            print("commit %s" % sha)
            print("Author: %s <%s>" % (name, email))
            print("Date:   %s" % _format_date(ts, tz))
            print()
            for line in message.rstrip("\n").splitlines():
                print("    %s" % line)
            print()
        sha = commit["parents"][0] if commit["parents"] else None
    return 0


def cmd_status(args):
    repo = find_repo()
    staged, unstaged, untracked = compute_status(repo)
    branch = repo.refs.current_branch()

    if args.short:
        codes = {}
        for kind, path in staged:
            x = {"new file": "A", "modified": "M", "deleted": "D"}[kind]
            codes.setdefault(path, [" ", " "])[0] = x
        for kind, path in unstaged:
            codes.setdefault(path, [" ", " "])[1] = (
                "M" if kind == "modified" else "D")
        for path, xy in sorted(codes.items()):
            print("".join(xy) + " " + path)
        for path in untracked:
            print("?? " + path)
        return 0

    print("On branch %s" % (branch or "HEAD (detached)"))
    if not repo.refs.head_commit():
        print("\nNo commits yet")
    if staged:
        print("\nChanges to be committed:")
        for kind, path in staged:
            print("\t%s:   %s" % (kind, path))
    if unstaged:
        print("\nChanges not staged for commit:")
        for kind, path in unstaged:
            print("\t%s:   %s" % (kind, path))
    if untracked:
        print("\nUntracked files:")
        for path in untracked:
            print("\t%s" % path)
    if not staged and not unstaged and not untracked:
        print("\nnothing to commit, working tree clean")
    return 0


def _diff_pairs(repo, cached):
    """Return {path: (old_text_or_None, new_text_or_None)} for the diff."""
    pairs = {}
    if cached:  # HEAD vs index
        head_map = head_tree_entries(repo)
        index = repo.index.entries
        for path in sorted(set(head_map) | set(index)):
            old = _read_blob_text(repo, head_map[path][1]) if path in head_map else None
            new = _read_blob_text(repo, index[path][1]) if path in index else None
            pairs[path] = (old, new)
    else:  # index vs working tree
        for path in sorted(repo.index.entries):
            old = _read_blob_text(repo, repo.index.entries[path][1])
            fpath = repo.abspath(path)
            new = _read_file_text(fpath) if os.path.isfile(fpath) else None
            pairs[path] = (old, new)
    return pairs


def cmd_diff(args):
    repo = find_repo()
    pairs = _diff_pairs(repo, args.cached)
    stats = []
    chunks = []
    for path, (old, new) in pairs.items():
        if old == new:
            continue
        if args.stat:
            added, deleted = diffutil.count_changes(old or "", new or "")
            stats.append((path, added, deleted))
        else:
            old_label = "a/" + path if old is not None else "/dev/null"
            new_label = "b/" + path if new is not None else "/dev/null"
            chunks.append("diff --minigit a/%s b/%s" % (path, path))
            chunks.append(diffutil.unified_diff(old or "", new or "",
                                                old_label, new_label))
    if args.stat:
        total_add = total_del = 0
        for path, added, deleted in stats:
            total_add += added
            total_del += deleted
            print(" %s | %d %s" % (path, added + deleted,
                                   "+" * added + "-" * deleted))
        if stats:
            print(" %d file(s) changed, %d insertion(s)(+), %d deletion(s)(-)"
                  % (len(stats), total_add, total_del))
    else:
        for chunk in chunks:
            print(chunk)
    return 0


def cmd_branch(args):
    repo = find_repo()
    if args.name is None:
        current = repo.refs.current_branch()
        for name in repo.refs.list_branches():
            print(("* " if name == current else "  ") + name)
        return 0
    if repo.refs.branch_exists(args.name):
        raise MiniGitError("branch already exists: %s" % args.name)
    head = repo.refs.head_commit()
    if not head:
        raise MiniGitError("no commits yet; cannot create a branch")
    repo.refs.write_branch(args.name, head)
    print("Created branch '%s' at %s" % (args.name, head[:7]))
    return 0


def cmd_checkout(args):
    repo = find_repo()
    name = args.branch
    if not repo.refs.branch_exists(name):
        raise MiniGitError("branch not found: %s" % name)
    if repo.refs.current_branch() == name:
        print("Already on '%s'" % name)
        return 0
    checkout_commit(repo, repo.refs.read_branch(name))
    repo.refs.set_head_branch(name)
    print("Switched to branch '%s'" % name)
    return 0


def cmd_reset(args):
    repo = find_repo()
    sha = resolve_commit(repo, args.commit)
    repo.refs.update_head(sha)
    if not args.soft:  # --mixed (default): also reset the index
        commit = parse_commit(repo.objects.read_object(sha)[1])
        repo.index.entries = flatten_tree(repo.objects, commit["tree"])
        repo.index.save()
    mode = "soft" if args.soft else "mixed"
    print("HEAD is now at %s (%s reset)" % (sha[:7], mode))
    return 0
