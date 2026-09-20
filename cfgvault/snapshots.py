"""Snapshot metadata objects and reference resolution."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .errors import InvalidReferenceError
from .objects import SNAPSHOT, iter_object_ids, read_object, write_object
from .refs import branch_file, branches_dir, read_branch

SNAPSHOT_VERSION = 1


def format_person(name: str, email: str) -> str:
    return f"{name} <{email}>"


def default_operator() -> str:
    name = (
        os.environ.get("CFGVAULT_OPERATOR")
        or os.environ.get("GIT_AUTHOR_NAME")
        or os.environ.get("USER")
        or os.environ.get("LOGNAME")
        or "operator"
    )
    email = os.environ.get("CFGVAULT_EMAIL") or os.environ.get("GIT_AUTHOR_EMAIL") or f"{name}@local"
    return format_person(name, email)


def now_timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def create_snapshot(
    root: Path,
    tree_oid: str,
    message: str,
    parent: Optional[str] = None,
    operator: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> str:
    """Create a snapshot JSON object and return its hash."""
    if not message or not message.strip():
        raise ValueError("snapshot message must not be empty")
    if parent is not None:
        parent_type, _ = read_object(root, parent)
        if parent_type != SNAPSHOT:
            raise InvalidReferenceError(f"snapshot parent {parent} is not a snapshot")
    tree_type, _ = read_object(root, tree_oid)
    if tree_type != "tree":
        raise InvalidReferenceError(f"snapshot tree {tree_oid} is not a tree")
    payload_obj = {
        "version": SNAPSHOT_VERSION,
        "tree": tree_oid,
        "parent": parent,
        "operator": operator or default_operator(),
        "date": timestamp or now_timestamp(),
        "message": message.strip(),
    }
    payload = (json.dumps(payload_obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )
    return write_object(root, SNAPSHOT, payload)


def parse_snapshot_payload(oid: str, payload: bytes) -> dict:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidReferenceError(f"snapshot {oid} has malformed metadata") from exc
    required = {"version", "tree", "parent", "operator", "date", "message"}
    if not isinstance(data, dict) or not required.issubset(data):
        raise InvalidReferenceError(f"snapshot {oid} has missing metadata fields")
    if data["version"] != SNAPSHOT_VERSION:
        raise InvalidReferenceError(f"snapshot {oid} uses unsupported version")
    if data["parent"] is not None and not isinstance(data["parent"], str):
        raise InvalidReferenceError(f"snapshot {oid} has invalid parent")
    return data


def read_snapshot(root: Path, oid: str) -> dict:
    object_type, payload = read_object(root, oid)
    if object_type != SNAPSHOT:
        raise InvalidReferenceError(f"object {oid} is {object_type}, expected snapshot")
    data = parse_snapshot_payload(oid, payload)
    data["oid"] = oid
    return data


def resolve_snapshot(root: Path, ref: Optional[str]) -> Optional[str]:
    """Resolve a branch, full hash, or unambiguous hash prefix to a snapshot."""
    if ref is None:
        return None
    # Branch names and 40-char hashes may overlap; branch reference wins.
    direct_branch = branch_file(root, ref)
    if direct_branch.exists():
        value = read_branch(root, ref)
        return value
    path = Path(ref)
    if not path.is_absolute() and len(ref.split("/")) >= 2:
        candidate = branches_dir(root) / ref
        if candidate.exists() and candidate.is_file():
            value = candidate.read_text(encoding="utf-8").strip()
            return value or None
    if len(ref) == 40:
        try:
            object_type, _ = read_object(root, ref)
        except (OSError, InvalidReferenceError) as exc:
            raise InvalidReferenceError(f"unknown snapshot reference: {ref}") from exc
        if object_type != SNAPSHOT:
            raise InvalidReferenceError(f"object {ref} is {object_type}, expected snapshot")
        return ref
    if len(ref) < 4:
        raise InvalidReferenceError(f"unknown snapshot reference: {ref}")
    try:
        int(ref, 16)
    except ValueError:
        raise InvalidReferenceError(f"unknown snapshot reference: {ref}")
    matches = []
    for oid in iter_object_ids(root):
        if oid.startswith(ref):
            object_type, _ = read_object(root, oid)
            if object_type == SNAPSHOT:
                matches.append(oid)
    if not matches:
        raise InvalidReferenceError(f"unknown snapshot reference: {ref}")
    if len(matches) > 1:
        joined = ", ".join(matches)
        raise InvalidReferenceError(f"snapshot reference {ref} is ambiguous: {joined}")
    return matches[0]


def snapshot_exists(root: Path, oid: str) -> bool:
    try:
        read_snapshot(root, oid)
    except Exception:
        return False
    return True
