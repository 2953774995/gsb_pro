"""Repository discovery, layout and initialisation."""

import os

from .errors import MiniGitError
from .ignore import IgnoreRules
from .index import Index
from .objects import ObjectStore
from .refs import RefStore

MINIGIT_DIR = ".minigit"
DEFAULT_BRANCH = "main"


class Repository:
    def __init__(self, workdir):
        self.workdir = os.path.abspath(workdir)
        self.gitdir = os.path.join(self.workdir, MINIGIT_DIR)
        self.objects = ObjectStore(self.gitdir)
        self.index = Index(self.gitdir).load()
        self.refs = RefStore(self.gitdir)
        self.ignore = IgnoreRules.from_file(os.path.join(self.workdir, ".minigitignore"))

    def abspath(self, relpath):
        return os.path.join(self.workdir, relpath)


def find_repo(start="."):
    """Walk upwards from ``start`` until a .minigit directory is found."""
    current = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(current, MINIGIT_DIR)):
            return Repository(current)
        parent = os.path.dirname(current)
        if parent == current:
            raise MiniGitError(
                "not a minigit repository (run 'minigit init' first)")
        current = parent


def init_repo(path="."):
    workdir = os.path.abspath(path)
    gitdir = os.path.join(workdir, MINIGIT_DIR)
    os.makedirs(os.path.join(gitdir, "objects"), exist_ok=True)
    os.makedirs(os.path.join(gitdir, "refs", "heads"), exist_ok=True)
    head = os.path.join(gitdir, "HEAD")
    if not os.path.exists(head):
        with open(head, "w", encoding="utf-8") as fh:
            fh.write("ref: refs/heads/%s\n" % DEFAULT_BRANCH)
    return gitdir
