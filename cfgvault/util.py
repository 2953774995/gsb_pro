"""Small filesystem and text helpers."""

from __future__ import annotations

import os
import tempfile
from typing import Union

PathLike = Union[str, os.PathLike[str]]


def normalize_relpath(path: str) -> str:
    """Return a canonical, POSIX-style relative repository path.

    Backslashes are retained in file names rather than treated as directory
    separators because cfgvault repositories use POSIX path semantics.
    """
    path = path.replace(os.sep, "/")
    if os.altsep:
        path = path.replace(os.altsep, "/")
    parts = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError(f"path escapes repository: {path!r}")
        parts.append(part)
    return "/".join(parts)


def atomic_write_bytes(path: PathLike, data: bytes) -> None:
    """Write a file atomically (same filesystem rename)."""
    path = os.fspath(path)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    stream = os.fdopen(fd, "wb")
    try:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
        stream.close()
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_text(path: PathLike, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def read_bytes(path: PathLike) -> bytes:
    with open(path, "rb") as stream:
        return stream.read()


def read_text(path: PathLike) -> str:
    return read_bytes(path).decode("utf-8")


def is_executable(mode: int) -> bool:
    return bool(mode & 0o111)
