"""Branch references and HEAD management."""

import os

from .errors import MiniGitError

_HEAD_PREFIX = "ref: refs/heads/"


class RefStore:
    def __init__(self, gitdir):
        self.gitdir = gitdir
        self.heads_dir = os.path.join(gitdir, "refs", "heads")
        self.head_file = os.path.join(gitdir, "HEAD")

    # -- HEAD ------------------------------------------------------------
    def current_branch(self):
        """Return the branch HEAD points at, or None when detached."""
        if not os.path.isfile(self.head_file):
            return None
        with open(self.head_file, "r", encoding="utf-8") as fh:
            content = fh.read().strip()
        if content.startswith(_HEAD_PREFIX):
            return content[len(_HEAD_PREFIX):]
        return None

    def set_head_branch(self, name):
        with open(self.head_file, "w", encoding="utf-8") as fh:
            fh.write("%s%s\n" % (_HEAD_PREFIX, name))

    def head_commit(self):
        """Return the commit sha HEAD currently points at, or None."""
        branch = self.current_branch()
        if branch is None:
            if not os.path.isfile(self.head_file):
                return None
            with open(self.head_file, "r", encoding="utf-8") as fh:
                return fh.read().strip() or None
        path = self._branch_path(branch)
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip() or None

    def update_head(self, sha):
        """Advance the ref HEAD points at (or detach HEAD to ``sha``)."""
        branch = self.current_branch()
        if branch is None:
            with open(self.head_file, "w", encoding="utf-8") as fh:
                fh.write(sha + "\n")
        else:
            self.write_branch(branch, sha)

    # -- branches ----------------------------------------------------------
    def _branch_path(self, name):
        if (not name or name in (".", "..") or name.startswith("-")
                or "/" in name or "\\" in name or name.endswith(".lock")):
            raise MiniGitError("invalid branch name: %r" % (name,))
        return os.path.join(self.heads_dir, name)

    def branch_exists(self, name):
        try:
            return os.path.isfile(self._branch_path(name))
        except MiniGitError:
            return False

    def list_branches(self):
        if not os.path.isdir(self.heads_dir):
            return []
        return sorted(os.listdir(self.heads_dir))

    def read_branch(self, name):
        path = self._branch_path(name)
        if not os.path.isfile(path):
            raise MiniGitError("branch not found: %s" % name)
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()

    def write_branch(self, name, sha):
        os.makedirs(self.heads_dir, exist_ok=True)
        with open(self._branch_path(name), "w", encoding="utf-8") as fh:
            fh.write(sha + "\n")
