"""Branch and HEAD reference management."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from .errors import InvalidReferenceError

DEFAULT_BRANCH = "main"
HEAD_FILE = Path(".cfgvault") / "HEAD"
BRANCHES_DIR = Path(".cfgvault") / "refs" / "heads"
_BRANCH_RE = re.compile(r"^\w[\w.-]*$", re.UNICODE)


def head_file(root: Path) -> Path:
    return root / HEAD_FILE


def branches_dir(root: Path) -> Path:
    return root / BRANCHES_DIR


def branch_file(root: Path, name: str) -> Path:
    validate_branch_name(name)
    return branches_dir(root) / name


def validate_branch_name(name: str) -> None:
    if not isinstance(name, str) or not name or name in (".", ".."):
        raise InvalidReferenceError(f"invalid branch name: {name!r}")
    if not _BRANCH_RE.fullmatch(name):
        raise InvalidReferenceError(
            f"invalid branch name {name!r}: use Unicode letters/numbers, '.', '_' or '-' and no path separators"
        )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".ref-", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def write_head(root: Path, branch_name: str) -> None:
    validate_branch_name(branch_name)
    _atomic_write(head_file(root), branch_name + "\n")


def current_branch(root: Path) -> str:
    path = head_file(root)
    if not path.exists():
        raise InvalidReferenceError("HEAD is missing")
    name = path.read_text(encoding="utf-8").strip()
    validate_branch_name(name)
    return name


def list_branches(root: Path) -> list[str]:
    base = branches_dir(root)
    if not base.exists():
        return []
    return sorted(
        item.name for item in base.iterdir() if item.is_file() and _BRANCH_RE.fullmatch(item.name)
    )


def branch_exists(root: Path, name: str) -> bool:
    try:
        return branch_file(root, name).exists()
    except InvalidReferenceError:
        return False


def create_branch(root: Path, name: str, snapshot_oid: str | None) -> None:
    validate_branch_name(name)
    destination = branch_file(root, name)
    if destination.exists():
        raise InvalidReferenceError(f"branch already exists: {name}")
    _atomic_write(destination, (snapshot_oid + "\n") if snapshot_oid else "")


def read_branch(root: Path, name: str) -> str | None:
    path = branch_file(root, name)
    if not path.exists():
        raise InvalidReferenceError(f"branch does not exist: {name}")
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def update_branch(root: Path, name: str, snapshot_oid: str) -> None:
    validate_branch_name(name)
    path = branch_file(root, name)
    if not path.exists():
        raise InvalidReferenceError(f"branch does not exist: {name}")
    _atomic_write(path, snapshot_oid + "\n")
