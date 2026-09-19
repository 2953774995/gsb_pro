"""The small .minigitignore pattern language."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Pattern:
    raw: str
    anchored: bool
    directory_only: bool
    regex: re.Pattern[str]

    def matches(self, path: str, is_dir: bool = False) -> bool:
        path = path.replace("\\", "/")
        if self.directory_only and not is_dir:
            return False
        if self.anchored:
            return bool(self.regex.fullmatch(path))
        return bool(self.regex.fullmatch(path)) or any(
            bool(self.regex.fullmatch("/".join(path.split("/")[index:])))
            for index in range(1, len(path.split("/")))
        )


def glob_to_regex(pattern: str) -> str:
    output = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                # ``**`` is accepted, though basic patterns normally use ``*``.
                output.append(".*")
                index += 2
                continue
            output.append("[^/]*")
        elif char == "?":
            output.append("[^/]")
        else:
            output.append(re.escape(char))
        index += 1
    output.append("$")
    return "".join(output)


def parse_pattern(raw_line: str) -> Pattern | None:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    directory_only = line.endswith("/")
    if directory_only:
        line = line[:-1]
    anchored = "/" in line.rstrip("/")
    if line.startswith("/"):
        anchored = True
        line = line[1:]
    if not line:
        return None
    return Pattern(raw_line, anchored, directory_only, re.compile(glob_to_regex(line)))


def read_patterns(path: Path) -> list[Pattern]:
    if not path.is_file():
        return []
    patterns: list[Pattern] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        pattern = parse_pattern(line)
        if pattern:
            patterns.append(pattern)
    return patterns


class IgnoreRules:
    def __init__(self, patterns: Iterable[Pattern] = ()):
        self.patterns = list(patterns)

    @classmethod
    def from_file(cls, path: Path) -> "IgnoreRules":
        return cls(read_patterns(path))

    def is_ignored(self, path: str, is_dir: bool = False) -> bool:
        clean = path.replace("\\", "/").strip("/")
        if clean == ".minigit" or clean.startswith(".minigit/"):
            return True
        return any(pattern.matches(clean, is_dir) for pattern in self.patterns)
