"""Repository discovery and directory layout."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .errors import MinigitError


class Repository:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.git_dir = self.root / ".minigit"
        self.objects_dir = self.git_dir / "objects"
        self.refs_dir = self.git_dir / "refs" / "heads"
        self.index_file = self.git_dir / "index"
        self.head_file = self.git_dir / "HEAD"
        self.ignore_file = self.root / ".minigitignore"

    def require(self) -> "Repository":
        if not self.git_dir.is_dir() or not self.objects_dir.is_dir():
            raise MinigitError("not a minigit repository (or any parent directory): run 'minigit init' first")
        return self

    def init(self) -> bool:
        existed = self.git_dir.is_dir()
        (self.objects_dir).mkdir(parents=True, exist_ok=True)
        (self.refs_dir).mkdir(parents=True, exist_ok=True)
        if not self.head_file.exists():
            self.head_file.write_text("ref: refs/heads/main\n", encoding="utf-8")
        if not self.index_file.exists():
            self.index_file.write_bytes(b"")
        return existed


def find_repository(start: Optional[Path] = None) -> Repository:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    while True:
        candidate = current / ".minigit"
        if candidate.is_dir():
            return Repository(current)
        if current.parent == current:
            # Error message is emitted through the same path regardless of cwd.
            return Repository(Path.cwd())
        current = current.parent
