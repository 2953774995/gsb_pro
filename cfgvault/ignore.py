"""Basic .cfgvaultignore pattern handling."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable, List

from .repo import Repository
from .util import read_text


def _translate_segment(glob: str) -> str:
    """Translate one shell-like path segment without allowing '/' globs."""
    result: List[str] = []
    index = 0
    while index < len(glob):
        char = glob[index]
        if char == "*":
            result.append("[^/]*")
        elif char == "?":
            result.append("[^/]")
        elif char == "[":
            end = glob.find("]", index + 1)
            if end != -1:
                expression = glob[index + 1 : end]
                if expression.startswith("!"):
                    expression = "^" + expression[1:]
                result.append("[" + expression + "]")
                index = end + 1
                continue
            result.append(re.escape(char))
        else:
            result.append(re.escape(char))
        index += 1
    return "".join(result)


def compile_pattern(pattern: str) -> re.Pattern:
    anchored = pattern.startswith("/")
    directory_only = pattern.endswith("/")
    bare = pattern.strip("/")
    body = "/".join(_translate_segment(part) for part in bare.split("/"))
    if anchored or "/" in bare:
        expression = r"^" + body + r"$"
    else:
        # A basename pattern matches at any directory depth.
        expression = r"^(?:.*/)?" + body + r"$"
    return re.compile(expression)


@dataclass(frozen=True)
class IgnoreRule:
    raw: str
    directory_only: bool
    regex: re.Pattern


class IgnoreRules:
    def __init__(self, rules: Iterable[IgnoreRule] = ()):
        self.rules = tuple(rules)

    def is_ignored(self, path: str, is_dir: bool = False) -> bool:
        normalized = path.replace(os.sep, "/").strip("/")
        parts = normalized.split("/") if normalized else []

        if is_dir:
            return any(rule.regex.match(normalized) for rule in self.rules)

        # A directory-only rule ignores all descendants of a matching dir.
        for depth in range(1, len(parts)):
            ancestor = "/".join(parts[:depth])
            if any(rule.directory_only and rule.regex.match(ancestor) for rule in self.rules):
                return True
        return any(
            not rule.directory_only and rule.regex.match(normalized)
            for rule in self.rules
        )


def parse_ignore_text(text: str) -> IgnoreRules:
    rules: List[IgnoreRule] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        directory_only = line.endswith("/")
        rules.append(IgnoreRule(line, directory_only, compile_pattern(line)))
    return IgnoreRules(rules)


def load_ignore_rules(repo: Repository) -> IgnoreRules:
    try:
        return parse_ignore_text(read_text(repo.ignore_file))
    except FileNotFoundError:
        return IgnoreRules()
