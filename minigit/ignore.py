"""Basic .minigitignore glob matching.

Supported pattern forms (gitignore-inspired, simplified):
  *.log          match any path component
  build/         directory-only match
  docs/*.md      match against the repo-relative path (contains '/')
  tmp?           '?' matches a single character
Blank lines and lines starting with '#' are skipped.
"""

import fnmatch
import os


class IgnoreRules:
    def __init__(self, patterns):
        self.rules = []  # (pattern, dir_only)
        for raw in patterns:
            pat = raw.strip()
            if not pat or pat.startswith("#"):
                continue
            dir_only = pat.endswith("/")
            pat = pat.strip("/")
            if pat:
                self.rules.append((pat, dir_only))

    @classmethod
    def from_file(cls, path):
        if not os.path.isfile(path):
            return cls([])
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return cls(fh.read().splitlines())

    def is_ignored(self, relpath, is_dir=False):
        relpath = relpath.replace(os.sep, "/").strip("/")
        if not relpath:
            return False
        parts = relpath.split("/")
        dir_parts = parts if is_dir else parts[:-1]
        for pat, dir_only in self.rules:
            if "/" in pat:
                # Path-anchored pattern: match the full path or any leading
                # directory prefix of it (so 'a/b' also ignores 'a/b/c').
                if fnmatch.fnmatchcase(relpath, pat):
                    return True
                for i in range(1, len(parts)):
                    if fnmatch.fnmatchcase("/".join(parts[:i]), pat):
                        return True
            else:
                # Bare pattern: match against any path component.
                targets = dir_parts if dir_only else parts
                if any(fnmatch.fnmatchcase(comp, pat) for comp in targets):
                    return True
        return False
