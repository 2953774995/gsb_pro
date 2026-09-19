"""Repository discovery and on-disk layout."""

import os

from .errors import MiniGitError

MINIGIT_DIR = ".minigit"
DEFAULT_BRANCH = "main"


class Repository(object):
    """Paths that make up a minigit repository."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.git_dir = os.path.join(self.root, MINIGIT_DIR)
        self.objects_dir = os.path.join(self.git_dir, "objects")
        self.refs_dir = os.path.join(self.git_dir, "refs")
        self.heads_dir = os.path.join(self.refs_dir, "heads")
        self.head_file = os.path.join(self.git_dir, "HEAD")
        self.index_file = os.path.join(self.git_dir, "index")
        self.ignore_file = os.path.join(self.root, ".minigitignore")

    def relpath(self, path):
        """Return *path* relative to the repo root, or None if outside."""
        apath = os.path.abspath(path)
        if apath == self.root:
            return ""
        prefix = self.root + os.sep
        if apath.startswith(prefix):
            return apath[len(prefix):]
        return None


def init_repo(path=None):
    """Create the .minigit directory structure under *path* (cwd by default)."""
    root = os.path.abspath(path or os.getcwd())
    repo = Repository(root)
    created = not os.path.isdir(repo.git_dir)
    for d in (repo.git_dir, repo.objects_dir, repo.refs_dir, repo.heads_dir):
        os.makedirs(d, exist_ok=True)
    if not os.path.exists(repo.head_file):
        with open(repo.head_file, "w", encoding="utf-8") as fh:
            fh.write("ref: refs/heads/%s\n" % DEFAULT_BRANCH)
    if not os.path.exists(repo.index_file):
        with open(repo.index_file, "w", encoding="utf-8") as fh:
            fh.write("")
    return repo, created


def find_repo(start=None):
    """Walk upwards from *start* (cwd by default) looking for a .minigit dir."""
    current = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isdir(os.path.join(current, MINIGIT_DIR)):
            return Repository(current)
        parent = os.path.dirname(current)
        if parent == current:
            raise MiniGitError(
                "fatal: not a minigit repository (or any parent up to mount point).\n"
                "Run 'minigit init' to create one."
            )
        current = parent
