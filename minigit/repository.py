"""Repository discovery and directory layout.

A minigit repository rooted at ``<root>`` contains the following layout::

    <root>/
    .minigit/
        HEAD                 # text file: "ref: refs/heads/main"
        index                # binary index (see index.py)
        objects/             # zlib-compressed, SHA-1 content-addressed
            ab/cdef...       # objects, split into 2-char dir + 38-char name
        refs/
            heads/<branch>   # one file per branch, content is a commit hash
"""

import os

from .errors import NotARepositoryError

GITDIR_NAME = ".minigit"
DEFAULT_BRANCH = "main"


class Repository:
    """A handle on an initialised minigit repository."""

    def __init__(self, root, gitdir):
        self.root = os.path.abspath(root)
        self.gitdir = os.path.abspath(gitdir)
        self.objects_dir = os.path.join(self.gitdir, "objects")
        self.refs_dir = os.path.join(self.gitdir, "refs", "heads")
        self.index_file = os.path.join(self.gitdir, "index")
        self.head_file = os.path.join(self.gitdir, "HEAD")

    # ------------------------------------------------------------------ paths
    def object_path(self, sha):
        """Return the on-disk path for object ``sha``."""
        return os.path.join(self.objects_dir, sha[:2], sha[2:])

    def branch_path(self, name):
        """Return the on-disk path for branch ``name``."""
        return os.path.join(self.refs_dir, name)

    # --------------------------------------------------------------- discovery
    @staticmethod
    def find(start=None):
        """Walk from ``start`` (default: cwd) upwards to find ``.minigit``.

        Raises :class:`NotARepositoryError` if no repository is found.
        """
        cur = os.path.abspath(start if start is not None else os.getcwd())
        while True:
            candidate = os.path.join(cur, GITDIR_NAME)
            if os.path.isdir(candidate):
                return Repository(cur, candidate)
            parent = os.path.dirname(cur)
            if parent == cur:
                raise NotARepositoryError(
                    "fatal: not a minigit repository (or any of the parent "
                    "directories): .minigit not found; run 'minigit init' first"
                )
            cur = parent

    @staticmethod
    def init(path=None):
        """Initialise a new repository in ``path`` (default cwd)."""
        root = os.path.abspath(path if path is not None else os.getcwd())
        gitdir = os.path.join(root, GITDIR_NAME)
        os.makedirs(os.path.join(gitdir, "objects"), exist_ok=True)
        os.makedirs(os.path.join(gitdir, "refs", "heads"), exist_ok=True)
        head = os.path.join(gitdir, "HEAD")
        if not os.path.exists(head):
            with open(head, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("ref: refs/heads/%s\n" % DEFAULT_BRANCH)
        # An empty index is written lazily on `add`; keep gitdir tidy.
        return Repository(root, gitdir)

    # --------------------------------------------------------------- relpaths
    def relpath(self, path):
        """Return the normalised repo-relative POSIX path for ``path``."""
        abspath = os.path.abspath(path)
        try:
            rel = os.path.relpath(abspath, self.root)
        except ValueError as exc:  # pragma: no cover - different drives
            raise PathError(str(exc))
        rel = rel.replace(os.sep, "/")
        if rel == "." or rel.startswith("../") or rel == "..":
            from .errors import PathError

            raise PathError("path is outside the repository: %r" % path)
        return rel
