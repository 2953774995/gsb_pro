"""HEAD, branch references and revision resolution."""

import os

from . import objects
from .errors import MiniGitError

_REF_PREFIX = "ref: refs/heads/"


def _read_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read().strip()


def _write_file(path, content):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.replace(tmp, path)


def current_branch(repo):
    """Return the checked-out branch name, or None when HEAD is detached."""
    if not os.path.exists(repo.head_file):
        return None
    content = _read_file(repo.head_file)
    if content.startswith(_REF_PREFIX):
        return content[len(_REF_PREFIX):]
    return None


def head_commit(repo):
    """Return the commit hash HEAD points at, or None on an unborn branch."""
    branch = current_branch(repo)
    if branch is not None:
        path = os.path.join(repo.heads_dir, branch)
        if os.path.exists(path):
            return _read_file(path)
        return None
    content = _read_file(repo.head_file)
    return content or None


def set_head_branch(repo, branch):
    _write_file(repo.head_file, "ref: refs/heads/%s\n" % branch)


def branch_path(repo, name):
    return os.path.join(repo.heads_dir, name)


def branch_exists(repo, name):
    return os.path.exists(branch_path(repo, name))


def read_branch(repo, name):
    return _read_file(branch_path(repo, name))


def list_branches(repo):
    if not os.path.isdir(repo.heads_dir):
        return []
    return sorted(os.listdir(repo.heads_dir))


def create_branch(repo, name, commit_oid):
    _write_file(branch_path(repo, name), commit_oid + "\n")


def update_head_ref(repo, commit_oid):
    """Advance the ref HEAD points at (or HEAD itself when detached)."""
    branch = current_branch(repo)
    if branch is not None:
        _write_file(branch_path(repo, branch), commit_oid + "\n")
    else:
        _write_file(repo.head_file, commit_oid + "\n")


def resolve_revision(repo, rev):
    """Resolve HEAD / branch name / full or abbreviated hash to a commit id."""
    if rev == "HEAD":
        oid = head_commit(repo)
        if oid is None:
            raise MiniGitError("fatal: HEAD does not point at a commit yet")
        return oid
    if branch_exists(repo, rev):
        return read_branch(repo, rev)
    try:
        oid = objects.find_object(repo, rev)
    except MiniGitError:
        raise MiniGitError("fatal: invalid commit reference: %s" % rev)
    obj_type, _ = objects.read_object(repo, oid)
    if obj_type != objects.COMMIT:
        raise MiniGitError("fatal: %s is not a commit" % rev)
    return oid
