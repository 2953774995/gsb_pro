"""References: HEAD pointer and ``refs/heads/<branch>``."""

import os
import re

from .errors import ObjectNotFoundError, RefNotFoundError, UsageError
from .index import load_index
from .objects import flatten_tree, object_exists, read_commit, read_object
from .repository import DEFAULT_BRANCH

_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-][A-Za-z0-9._/-]*$")


def validate_branch_name(name):
    if not name or name.startswith(("-", ".", "/")) or name.endswith(("/", ".", "-")):
        raise UsageError("fatal: not a valid branch name: %r" % name)
    if ".." in name or "//" in name or "@{" in name or "\\" in name:
        raise UsageError("fatal: not a valid branch name: %r" % name)
    if not _BRANCH_RE.match(name):
        raise UsageError("fatal: not a valid branch name: %r" % name)
    return name


# ---------------------------------------------------------------------- HEAD
def read_head_symbolic(repo):
    """Return the current branch name from ``HEAD`` ("ref: refs/heads/x")."""
    with open(repo.head_file, "r", encoding="utf-8") as fh:
        content = fh.read().strip()
    prefix = "ref: refs/heads/"
    if not content.startswith(prefix):
        raise UsageError("fatal: detached HEAD is not supported by minigit")
    return content[len(prefix) :]


def write_head_symbolic(repo, branch):
    with open(repo.head_file, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("ref: refs/heads/%s\n" % branch)


def current_branch(repo):
    return read_head_symbolic(repo)


# -------------------------------------------------------------------- branches
def list_branches(repo):
    """Return ``[(name, sha_or_None), ...]`` sorted by name."""
    out = []
    if os.path.isdir(repo.refs_dir):
        for name in sorted(os.listdir(repo.refs_dir)):
            out.append((name, read_branch(repo, name)))
    return out


def branch_exists(repo, name):
    return os.path.exists(repo.branch_path(name))


def read_branch(repo, name):
    path = repo.branch_path(name)
    if not os.path.exists(path):
        raise RefNotFoundError("fatal: branch %r does not exist" % name)
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read().strip()


def write_branch(repo, name, sha):
    validate_branch_name(name)
    path = repo.branch_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(sha + "\n")


def head_commit(repo):
    """Return current HEAD commit sha, or ``None`` if the branch is unborn."""
    branch = read_head_symbolic(repo)
    path = repo.branch_path(branch)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        sha = fh.read().strip()
    if not sha:
        return None
    return sha


def update_ref(repo, name, sha):
    write_branch(repo, name, sha)


# --------------------------------------------------------------- refs resolve
def resolve(repo, refish):
    """Resolve a commit reference given as a branch name or (possibly
    abbreviated) object hash.  Raises ObjectNotFoundError on failure.
    """
    if refish == "HEAD":
        sha = head_commit(repo)
        if sha is None:
            raise ObjectNotFoundError("fatal: unknown revision 'HEAD'")
        return sha

    # Exact object hash first.
    if re.fullmatch(r"[0-9a-f]{40}", refish) and object_exists(repo, refish):
        return refish

    # Branch name.
    path = repo.branch_path(refish)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()

    # Abbreviated hash: unique prefix matching a loose object.
    if re.fullmatch(r"[0-9a-f]{4,39}", refish):
        prefix_dir = os.path.join(repo.objects_dir, refish[:2])
        if os.path.isdir(prefix_dir):
            matches = []
            rest = refish[2:]
            for fname in os.listdir(prefix_dir):
                if fname.startswith(rest):
                    matches.append(refish[:2] + fname)
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise ObjectNotFoundError(
                    "fatal: short SHA %r is ambiguous (%d objects match)"
                    % (refish, len(matches))
                )

    raise ObjectNotFoundError("fatal: unknown revision %r" % refish)


def resolve_commit(repo, refish):
    """Like :func:`resolve` but guarantees the result is a commit object."""
    sha = resolve(repo, refish)
    obj_type, _ = read_object(repo, sha)
    if obj_type != "commit":
        raise ObjectNotFoundError("fatal: %s is not a commit" % sha[:12])
    return sha


# --------------------------------------------------------------- tree helpers
def head_tree_entries(repo):
    """Return ``{path: (mode, sha)}`` of the current HEAD commit tree, or {}."""
    sha = head_commit(repo)
    if sha is None:
        return {}
    commit = read_commit(repo, sha)
    return flatten_tree(repo, commit["tree"])
