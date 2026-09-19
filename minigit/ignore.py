""".minigitignore pattern matching.

Supported syntax (a practical subset of .gitignore):
  * blank lines and lines starting with '#' are ignored
  * '!' negates a previous match
  * trailing '/' matches directories only
  * patterns containing '/' are anchored to the repository root
  * patterns without '/' match against any path component
  * glob wildcards: '*', '?', '[...]'
The .minigit directory itself is always ignored.
"""

import fnmatch
import os

from .repo import MINIGIT_DIR


class IgnoreRules(object):
    def __init__(self, patterns=None):
        # patterns: list of (negated, dir_only, anchored, pattern)
        self.patterns = list(patterns or [])

    @classmethod
    def from_file(cls, path):
        rules = cls()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    rules.add(raw.rstrip("\n"))
        return rules

    @classmethod
    def from_repo(cls, repo):
        return cls.from_file(repo.ignore_file)

    def add(self, line):
        line = line.strip()
        if not line or line.startswith("#"):
            return
        negated = line.startswith("!")
        if negated:
            line = line[1:]
        dir_only = line.endswith("/")
        if dir_only:
            line = line.rstrip("/")
        anchored = line.startswith("/")
        line = line.lstrip("/")
        if not line:
            return
        if "/" in line:
            anchored = True
        self.patterns.append((negated, dir_only, anchored, line))

    def matches(self, relpath, is_dir=False):
        """True if *relpath* (repo-relative, '/'-separated) is ignored."""
        relpath = relpath.replace(os.sep, "/").strip("/")
        if not relpath:
            return False
        parts = relpath.split("/")
        if parts[0] == MINIGIT_DIR:
            return True
        ignored = False
        for negated, dir_only, anchored, pattern in self.patterns:
            if dir_only and not is_dir:
                continue
            if anchored:
                hit = fnmatch.fnmatchcase(relpath, pattern)
            else:
                hit = any(fnmatch.fnmatchcase(part, pattern) for part in parts)
            if hit:
                ignored = not negated
        return ignored
