"""Commit object parsing and serialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import localtime, strftime
from typing import Iterable, Optional

from . import objects
from .objects import OBJECT_COMMIT


@dataclass
class Commit:
    tree: str
    parents: list[str] = field(default_factory=list)
    author: str = "minigit <minigit@localhost>"
    author_time: Optional[int] = None
    author_tz: str = "+0000"
    committer: Optional[str] = None
    committer_time: Optional[int] = None
    committer_tz: Optional[str] = None
    message: str = ""


def _timestamp(seconds: Optional[int], timezone: str, timestamp_prefix: str, name_line: str) -> bytes:
    import time

    seconds = int(seconds if seconds is not None else time.time())
    return (
        f"{timestamp_prefix} {name_line} {seconds} {timezone}\n".encode("utf-8")
    )


def serialize_commit(commit: Commit) -> bytes:
    committer = commit.committer or commit.author
    committer_tz = commit.committer_tz or commit.author_tz
    committer_time = commit.committer_time if commit.committer_time is not None else commit.author_time
    lines = [f"tree {commit.tree}"]
    lines.extend(f"parent {parent}" for parent in commit.parents)
    result = ("\n".join(lines) + "\n").encode("utf-8")
    result += _timestamp(commit.author_time, commit.author_tz, "author", commit.author)
    result += _timestamp(committer_time, committer_tz, "committer", committer)
    result += b"\n" + commit.message.encode("utf-8")
    if result and not result.endswith(b"\n"):
        result += b"\n"
    return result


def write_commit(objects_dir, commit: Commit) -> str:
    return objects.write_object(objects_dir, OBJECT_COMMIT, serialize_commit(commit))


def parse_commit(data: bytes) -> Commit:
    header, separator, message = data.partition(b"\n\n")
    if not separator:
        raise ValueError("invalid commit: missing message separator")
    parents: list[str] = []
    tree = ""
    author = ""
    author_time = None
    author_tz = "+0000"
    committer = ""
    committer_time = None
    committer_tz = "+0000"
    for line in header.decode("utf-8").splitlines():
        if line.startswith("tree "):
            tree = line[5:].strip()
        elif line.startswith("parent "):
            parents.append(line[7:].strip())
        elif line.startswith("author "):
            author, author_time, author_tz = _parse_person_time(line[7:])
        elif line.startswith("committer "):
            committer, committer_time, committer_tz = _parse_person_time(line[10:])
    if not tree:
        raise ValueError("invalid commit: missing tree")
    return Commit(
        tree=tree,
        parents=parents,
        author=author,
        author_time=author_time,
        author_tz=author_tz,
        committer=committer or author,
        committer_time=committer_time,
        committer_tz=committer_tz,
        message=message.decode("utf-8"),
    )


def _parse_person_time(value: str) -> tuple[str, int, str]:
    pieces = value.rsplit(" ", 2)
    if len(pieces) != 3:
        return value, 0, "+0000"
    person, seconds, timezone = pieces
    return person, int(seconds), timezone


def read_commit(objects_dir, sha: str) -> Commit:
    return parse_commit(objects.read_object(objects_dir, sha, OBJECT_COMMIT)[1])


def format_commit_date(commit: Commit) -> str:
    if commit.author_time is None:
        return ""
    return strftime("%Y-%m-%d %H:%M:%S", localtime(commit.author_time)) + f" {commit.author_tz}"


def chain(objects_dir, start: Optional[str]) -> Iterable[tuple[str, Commit]]:
    seen = set()
    current = start
    while current:
        if current in seen:
            raise ValueError(f"commit history forms a cycle at {current}")
        seen.add(current)
        commit = read_commit(objects_dir, current)
        yield current, commit
        current = commit.parents[0] if commit.parents else None
