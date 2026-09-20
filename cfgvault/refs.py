"""HEAD and branch reference management."""

from __future__ import annotations

import os
import re
from typing import Optional

from .errors import InvalidArgumentError, InvalidObjectError, InvalidReferenceError
from .objects import read_object, validate_oid
from .repo import DEFAULT_BRANCH, Repository
from .util import atomic_write_text, read_text

# Conservative but Unicode-friendly branch names.  Slashes allow hierarchy,
# while path traversal and filesystem-hostile names are rejected.
_BRANCH_RE = re.compile(r"^[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff._/-]*$")


def validate_branch_name(name: str) -> str:
    if not name or not isinstance(name, str):
        raise InvalidArgumentError("branch name is required")
    if name in (".", "..") or name.startswith("-") or name.endswith(("/", ".", ".lock")):
        raise InvalidArgumentError(f"invalid branch name: {name}")
    if "//" in name or "/." in name or "/.." in name or ".." in name:
        raise InvalidArgumentError(f"invalid branch name: {name}")
    if not _BRANCH_RE.match(name):
        raise InvalidArgumentError(f"invalid branch name: {name}")
    return name


def read_head_name(repo: Repository) -> str:
    try:
        name = read_text(repo.head_file).strip()
    except FileNotFoundError as exc:
        raise InvalidReferenceError("HEAD is missing; run 'cfgvault init'") from exc
    if not name:
        return DEFAULT_BRANCH
    return validate_branch_name(name)


def set_head_name(repo: Repository, name: str) -> None:
    validate_branch_name(name)
    atomic_write_text(repo.head_file, name + "\n")


def ref_path(repo: Repository, name: str) -> str:
    validate_branch_name(name)
    return repo.ref_file(name)


def list_branches(repo: Repository) -> list[str]:
    if not os.path.isdir(repo.refs_dir):
        return []
    names: list[str] = []
    for base, dirs, files in os.walk(repo.refs_dir):
        dirs.sort()
        for filename in sorted(files):
            full = os.path.join(base, filename)
            rel = os.path.relpath(full, repo.refs_dir).replace(os.sep, "/")
            names.append(rel)
    return sorted(names)


def branch_exists(repo: Repository, name: str) -> bool:
    return os.path.isfile(ref_path(repo, name))


def create_branch(repo: Repository, name: str, snapshot_oid: Optional[str]) -> None:
    validate_branch_name(name)
    path = ref_path(repo, name)
    if os.path.exists(path):
        raise InvalidArgumentError(f"branch already exists: {name}")
    if snapshot_oid is not None:
        validate_oid(snapshot_oid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_write_text(path, ("" if snapshot_oid is None else snapshot_oid) + ("\n" if snapshot_oid else ""))


def read_branch_oid(repo: Repository, name: str, required: bool = True) -> Optional[str]:
    path = ref_path(repo, name)
    if not os.path.isfile(path):
        if required:
            raise InvalidReferenceError(f"branch does not exist: {name}")
        return None
    value = read_text(path).strip()
    if not value:
        return None
    validate_oid(value)
    return value


def update_branch(repo: Repository, name: str, snapshot_oid: str) -> None:
    validate_branch_name(name)
    path = ref_path(repo, name)
    if not os.path.exists(path):
        raise InvalidReferenceError(f"branch does not exist: {name}")
    validate_oid(snapshot_oid)
    atomic_write_text(path, snapshot_oid + "\n")


def read_head_oid(repo: Repository) -> Optional[str]:
    return read_branch_oid(repo, read_head_name(repo), required=True)


def resolve_object_prefix(repo: Repository, expression: str) -> str:
    """Resolve a full id or an unambiguous short hex prefix."""
    expression = expression.strip()
    allowed = set("0123456789abcdefABCDEF")
    if not expression or len(expression) < 4 or any(c not in allowed for c in expression):
        raise InvalidReferenceError(f"invalid snapshot reference: {expression}")
    prefix = expression.lower()
    if len(prefix) == 40:
        try:
            read_object(repo, prefix)
        except InvalidObjectError as exc:
            raise InvalidReferenceError(f"snapshot not found: {expression}") from exc
        return prefix

    matches = []
    directory = os.path.join(repo.objects_dir, prefix[:2])
    remainder = prefix[2:]
    if os.path.isdir(directory):
        for filename in os.listdir(directory):
            if len(filename) == 38 and filename.startswith(remainder):
                matches.append(prefix[:2] + filename)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise InvalidReferenceError(f"snapshot not found: {expression}")
    raise InvalidReferenceError(f"short snapshot reference is ambiguous: {expression}")

def resolve_snapshot(repo: Repository, expression: Optional[str]) -> str:
    """Resolve HEAD, a branch name, full id, or short id to a snapshot id."""
    if expression is None or expression in ("HEAD", "@"):
        oid = read_head_oid(repo)
        if oid is None:
            raise InvalidReferenceError("current branch has no snapshots")
        return oid

    # Branch names may look like short hashes only rarely; named refs win.
    candidate_ref = ref_path_for_lookup(repo, expression)
    if candidate_ref is not None and os.path.isfile(candidate_ref):
        oid = read_text(candidate_ref).strip()
        if not oid:
            raise InvalidReferenceError(f"branch has no snapshots: {expression}")
        return oid

    oid = resolve_object_prefix(repo, expression)
    object_type, _ = read_object(repo, oid)
    if object_type != "snapshot":
        raise InvalidReferenceError(f"reference is a {object_type}, not a snapshot: {expression}")
    return oid


def ref_path_for_lookup(repo: Repository, expression: str) -> Optional[str]:
    # Avoid rejecting valid raw hash-like branch names during lookup; branch
    # creation remains protected by validate_branch_name.
    if "\n" in expression or "/" in expression and ".." in expression:
        return None
    if expression.startswith(".") or "\x00" in expression:
        return None
    path = os.path.join(repo.refs_dir, *expression.split("/"))
    refs_dir = os.path.abspath(repo.refs_dir)
    abs_path = os.path.abspath(path)
    if abs_path == refs_dir or not (abs_path == refs_dir or abs_path.startswith(refs_dir + os.sep)):
        return None
    return path
