""".cfgvaultignore pattern handling."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

IGNORE_FILE_NAME = ".cfgvaultignore"
_CONFIG_DIR_NAME = ".cfgvault"
_VCS_DIR_NAME = ".git"


def _translate_basic_glob(pattern: str) -> str:
    out = ["^"]
    for char in pattern:
        if char == "*":
            out.append(r"[^/]*")
        elif char == "?":
            out.append(r"[^/]")
        elif char == "/":
            out.append("/")
        else:
            out.append(re.escape(char))
    out.append(r"$")
    return "".join(out)


class IgnoreRules:
    """Matcher for the subset of glob rules required by the PRD."""

    def __init__(self, patterns: Iterable[str] = ()):
        self._patterns = tuple(patterns)
        rules = []
        for raw in self._patterns:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            directory_only = line.endswith("/")
            if directory_only:
                line = line[:-1]
            anchored = line.startswith("/") or "/" in line
            if line.startswith("/"):
                line = line[1:]
            if not line:
                continue
            rules.append((re.compile(_translate_basic_glob(line)), anchored, directory_only))
        self._rules = tuple(rules)

    @property
    def patterns(self) -> tuple[str, ...]:
        return self._patterns

    def matches(self, path: str, is_dir: bool = False) -> bool:
        if os.sep != "/":
            path = path.replace(os.sep, "/")
        if (
            path == _CONFIG_DIR_NAME
            or path.startswith(_CONFIG_DIR_NAME + "/")
            or path == _VCS_DIR_NAME
            or path.startswith(_VCS_DIR_NAME + "/")
        ):
            return True
        normalized = path.strip("/")
        base = normalized.rsplit("/", 1)[-1]
        for regex, anchored, directory_only in self._rules:
            if directory_only and not is_dir:
                continue
            candidates = (normalized,) if anchored else (base, normalized)
            if any(regex.match(candidate) for candidate in candidates):
                return True
        return False


def load_ignore_rules(root: Path) -> IgnoreRules:
    path = root / IGNORE_FILE_NAME
    if not path.exists():
        return IgnoreRules()
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return IgnoreRules()
    return IgnoreRules(text.splitlines())
