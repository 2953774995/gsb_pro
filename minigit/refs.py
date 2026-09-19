"""HEAD and branch reference management."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .errors import MinigitError
from .repository import Repository

REF_PREFIX = "ref: refs/heads/"
BRANCH_RE = re.compile(r"^(?!/|.*//)(?!.*\.\.)[A-Za-z0-9._/-]+(?<!\.|/)$")


def current_branch(repo: Repository) -> str:
    try:
        content = repo.head_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise MinigitError("HEAD is missing; run 'minigit init'") from None
    if not content.startswith(REF_PREFIX):
        raise MinigitError("invalid HEAD: expected a branch reference")
    branch = content[len(REF_PREFIX) :]
    if not valid_branch_name(branch):
        raise MinigitError(f"invalid branch name in HEAD: {branch!r}")
    return branch


def switch_branch(repo: Repository, branch: str) -> None:
    if not valid_branch_name(branch):
        raise MinigitError(f"invalid branch name: {branch!r}")
    repo.head_file.write_text(REF_PREFIX + branch + "\n", encoding="utf-8")


def branch_file(repo: Repository, branch: str) -> Path:
    if not valid_branch_name(branch):
        raise MinigitError(f"invalid branch name: {branch!r}")
    path = (repo.refs_dir / branch).resolve()
    try:
        path.relative_to(repo.refs_dir.resolve())
    except ValueError:
        raise MinigitError(f"invalid branch name: {branch!r}") from None
    return path


def valid_branch_name(name: str) -> bool:
    if not name or name in (".", "..") or name.startswith("-"):
        return False
    if any(part in (".", "..") or part.endswith(".") for part in name.split("/")):
        return False
    return bool(BRANCH_RE.match(name)) and "@{" not in name


def list_branches(repo: Repository) -> list[str]:
    result: list[str] = []
    if repo.refs_dir.exists():
        for path in sorted(repo.refs_dir.rglob("*"), key=lambda p: str(p.relative_to(repo.refs_dir))):
            if path.is_file():
                result.append(str(path.relative_to(repo.refs_dir)))
    return result


def read_branch(repo: Repository, branch: str) -> Optional[str]:
    path = branch_file(repo, branch)
    if not path.exists():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def write_branch(repo: Repository, branch: str, commit_hash: str) -> None:
    path = branch_file(repo, branch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(commit_hash + "\n", encoding="utf-8")


def head_commit(repo: Repository) -> Optional[str]:
    return read_branch(repo, current_branch(repo))


def resolve_commit(repo: Repository, expression: Optional[str] = None) -> Optional[str]:
    """Resolve HEAD, branch names, full IDs, and unambiguous short object IDs."""
    if expression is None or expression == "HEAD":
        value = head_commit(repo)
        if expression is not None and not value:
            raise MinigitError("HEAD does not point to a commit yet")
        return value

    if expression.startswith("-"):
        raise MinigitError(f"invalid commit reference: {expression}")
    # Branch can be a short or nested name.
    branch = read_branch(repo, expression)
    if branch:
        return branch.strip()

    candidate = expression.lower()
    if all(c in "0123456789abcdef" for c in candidate):
        if len(candidate) == 40:
            from . import objects

            if objects.exists(repo.objects_dir, candidate):
                objects.read_object(repo.objects_dir, candidate, objects.OBJECT_COMMIT)
                return candidate
            raise MinigitError(f"commit not found: {expression}")
        if len(candidate) >= 4:
            prefix_dir = repo.objects_dir / candidate[:2]
            matches = []
            if prefix_dir.is_dir():
                suffix = candidate[2:]
                matches = [candidate[:2] + p.name for p in prefix_dir.iterdir() if p.is_file() and p.name.startswith(suffix)]
            commit_matches: list[str] = []
            from . import objects

            for match in matches:
                object_type, _ = objects.read_object(repo.objects_dir, match)
                if object_type == objects.OBJECT_COMMIT:
                    commit_matches.append(match)
            if len(commit_matches) == 1:
                return commit_matches[0]
            if len(commit_matches) > 1:
                raise MinigitError(f"short commit {expression} is ambiguous")
    raise MinigitError(f"unknown commit reference: {expression}")
