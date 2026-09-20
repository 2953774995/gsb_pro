"""Repository discovery and initialization."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .errors import CfgvaultError, NotARepositoryError
from .util import atomic_write_bytes

DEFAULT_BRANCH = "main"
CFG_DIR = ".cfgvault"


@dataclass(frozen=True)
class Repository:
    """A discovered cfgvault repository.

    ``root`` is the working tree root and ``dir`` is its ``.cfgvault``
    metadata directory.
    """

    root: str
    dir: str

    @property
    def objects_dir(self) -> str:
        return os.path.join(self.dir, "objects")

    @property
    def refs_dir(self) -> str:
        return os.path.join(self.dir, "refs", "heads")

    @property
    def head_file(self) -> str:
        return os.path.join(self.dir, "HEAD")

    @property
    def index_file(self) -> str:
        return os.path.join(self.dir, "index")

    @property
    def ignore_file(self) -> str:
        return os.path.join(self.root, ".cfgvaultignore")

    def ref_file(self, branch: str) -> str:
        return os.path.join(self.refs_dir, *branch.split("/"))


def find_repository(start: Optional[str] = None) -> Repository:
    """Find a repository by walking upward from ``start`` (default: cwd)."""
    current = os.path.abspath(start or os.getcwd())
    while True:
        meta = os.path.join(current, CFG_DIR)
        if os.path.isdir(meta):
            return Repository(current, meta)
        parent = os.path.dirname(current)
        if parent == current:
            raise NotARepositoryError(
                "cfgvault: not a cfgvault repository (or any parent directory): "
                ".cfgvault not found; run 'cfgvault init' first"
            )
        current = parent


def require_repository(start: Optional[str] = None) -> Repository:
    """Public alias for :func:`find_repository`."""
    return find_repository(start)


def init_repository(path: Optional[str] = None) -> Repository:
    """Create a new repository.

    Initialization is idempotent: an existing valid repository is returned
    without overwriting HEAD, refs, index, or objects.
    """
    root = os.path.abspath(path or os.getcwd())
    meta = os.path.join(root, CFG_DIR)
    repo = Repository(root, meta)
    os.makedirs(repo.objects_dir, exist_ok=True)
    os.makedirs(repo.refs_dir, exist_ok=True)

    if not os.path.isfile(repo.head_file):
        atomic_write_bytes(repo.head_file, (DEFAULT_BRANCH + "\n").encode("utf-8"))
    default_ref = repo.ref_file(DEFAULT_BRANCH)
    if not os.path.isfile(default_ref):
        # A zero-byte ref means "no snapshot yet"; it reserves the branch name.
        atomic_write_bytes(default_ref, b"")
    if not os.path.isfile(repo.index_file):
        # Versioned binary index, initially containing zero entries.
        atomic_write_bytes(repo.index_file, b"CFGVLTIDX\n1\n")

    # Basic sanity checks: initialization over a file should never silently
    # produce a broken repository.
    if not os.path.isdir(repo.objects_dir):
        raise CfgvaultError(f"cfgvault: cannot create object directory: {repo.objects_dir}")
    return repo


def worktree_path(repo: Repository, relpath: str) -> str:
    """Join a validated relative path with the worktree root."""
    if os.path.isabs(relpath):
        raise CfgvaultError(f"cfgvault: expected a relative repository path: {relpath}")
    return os.path.join(repo.root, *relpath.split("/"))


def relative_worktree_path(repo: Repository, abs_path: str) -> str:
    root = os.path.abspath(repo.root)
    target = os.path.abspath(abs_path)
    try:
        return Path(target).relative_to(root).as_posix()
    except ValueError as exc:
        raise CfgvaultError(f"cfgvault: path is outside repository: {abs_path}") from exc
