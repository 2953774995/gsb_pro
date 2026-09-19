"""Parsing and matching of ``.minigitignore`` rules.

Supported pattern semantics (basic glob)::

    # comment and blank lines are ignored
    foo.txt          matches a file or directory named foo.txt at any depth
    build/           matches a directory named build at any depth
    /main.log        anchored: matches only main.log at the repo root
    docs/note.md     anchored (contains a slash): root-relative match
    *.log            ``*`` matches any run of non-slash characters
    file?.txt        ``?`` matches exactly one non-slash character
    src/*.py         anchored glob with a directory component

Negation (``!``) is intentionally not supported (such lines are
ignored).  Matching is case-sensitive and uses POSIX-style relative
paths (``a/b/c``).
"""

import os
import re

GITDIR_NAME = ".minigit"
IGNORE_FILE = ".minigitignore"


def _glob_to_re(pattern):
    """Translate a glob (``*`` / ``?``) into a full-match regex.

    Unlike :func:`fnmatch.translate`, ``*`` never matches ``/``.
    """
    out = ["^"]
    for ch in pattern:
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
    out.append(r"\Z")
    return "".join(out)


_GLOB_CACHE = {}


def _compile(pattern):
    if pattern not in _GLOB_CACHE:
        _GLOB_CACHE[pattern] = re.compile(_glob_to_re(pattern))
    return _GLOB_CACHE[pattern]


class IgnoreRule:
    def __init__(self, raw):
        self.raw = raw
        pat = raw
        self.directory_only = pat.endswith("/")
        if self.directory_only:
            pat = pat[:-1]
        self.leading_slash = pat.startswith("/")
        # A pattern is root-anchored if it contains a slash anywhere
        # other than (possibly) the very beginning.
        self.anchored = ("/" in pat) and not (
            self.leading_slash and pat.count("/") == 1
        )
        if self.leading_slash:
            pat = pat[1:]
        self.pattern = pat
        self.regex = _compile(pat)

    def matches(self, relpath, is_dir):
        """Check a POSIX relative path for a file or directory.

        A slash-free pattern matches any path component (so ``*.log``
        matches ``a/b.log``); a pattern containing a slash is anchored to
        the repository root and matched against the whole path.
        """
        if self.directory_only and not is_dir:
            return False
        if self.anchored:
            # Multi-segment pattern (e.g. docs/a.md, /a/b): match whole path.
            return self.regex.match(relpath) is not None
        if self.leading_slash:
            # Single-segment anchored name (e.g. /foo): root file only.
            return self.regex.match(relpath) is not None
        # Unanchored, slash-free: match any single path component.
        return any(
            self.regex.match(part) is not None
            for part in relpath.split("/")
        )


def parse_rules(text):
    rules = []
    for line in text.splitlines():
        line = line.rstrip("\r\n").strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        rules.append(IgnoreRule(line))
    return rules


class IgnoreMatcher:
    """Matches paths against the root ``.minigitignore`` rules."""

    def __init__(self, rules=None):
        self.rules = list(rules or [])

    @classmethod
    def for_repo(cls, repo):
        path = os.path.join(repo.root, IGNORE_FILE)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return cls(parse_rules(fh.read()))
        except FileNotFoundError:
            return cls()

    def is_ignored(self, relpath, is_dir=False):
        # The metadata directory is *always* ignored.
        if relpath == GITDIR_NAME or relpath.startswith(GITDIR_NAME + "/"):
            return True
        for rule in self.rules:
            if rule.matches(relpath, is_dir):
                return True
        return False


def walk_files(repo, matcher=None):
    """Return ``[(relpath, abspath), ...]`` of non-ignored working-tree files.

    Ignored directories are pruned so nothing beneath them is reported;
    ``.minigit`` is always pruned.  Results are sorted by path for
    deterministic behaviour.
    """
    if matcher is None:
        matcher = IgnoreMatcher()
    results = []

    def _walk(dir_abs, rel_prefix):
        try:
            names = sorted(os.listdir(dir_abs))
        except FileNotFoundError:
            return
        for name in names:
            abspath = os.path.join(dir_abs, name)
            relpath = rel_prefix + name if rel_prefix else name
            if os.path.isdir(abspath) and not os.path.islink(abspath):
                if matcher.is_ignored(relpath, is_dir=True):
                    continue
                _walk(abspath, relpath + "/")
            elif os.path.isfile(abspath):
                if matcher.is_ignored(relpath, is_dir=False):
                    continue
                results.append((relpath, abspath))

    _walk(repo.root, "")
    results.sort(key=lambda item: item[0])
    return results
