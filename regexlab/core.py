"""Compiled pattern objects, match results and the module-level API."""

from . import engine
from .errors import RegexError
from .parser import parse

__all__ = ["RegexError", "Pattern", "Match", "compile", "match", "search",
           "fullmatch", "findall", "finditer", "purge"]

# Cache of recently compiled patterns, mirroring re's internal cache.
_CACHE = {}
_CACHE_MAX = 128


class Match:
    """The result of a successful match, modelled after ``re.Match``."""

    def __init__(self, pattern, string, spans):
        self.re = pattern
        self.string = string
        self._spans = spans  # list indexed by group number, 0 = whole match

    # -- group access ---------------------------------------------------

    def group(self, *ids):
        """Return one or more matched substrings.

        ``group(0)`` (or ``group()``) is the whole match; ``group(n)``
        is the n-th capturing group or None if it did not participate.
        """
        if not ids:
            ids = (0,)
        results = []
        for i in ids:
            span = self._span_for(i)
            results.append(None if span is None
                           else self.string[span[0]:span[1]])
        return results[0] if len(results) == 1 else tuple(results)

    def groups(self, default=None):
        """Return a tuple of all capturing groups (1..n)."""
        return tuple(
            default if self._spans[i] is None else
            self.string[self._spans[i][0]:self._spans[i][1]]
            for i in range(1, len(self._spans))
        )

    # -- positions --------------------------------------------------------

    def _span_for(self, i):
        if not isinstance(i, int):
            raise IndexError("group indices must be integers")
        if i < 0 or i >= len(self._spans):
            raise IndexError("no such group: %r" % i)
        return self._spans[i]

    def start(self, group=0):
        span = self._span_for(group)
        return -1 if span is None else span[0]

    def end(self, group=0):
        span = self._span_for(group)
        return -1 if span is None else span[1]

    def span(self, group=0):
        span = self._span_for(group)
        return (-1, -1) if span is None else span

    def __repr__(self):
        return "<regexlab.Match span=%r match=%r>" % (self.span(),
                                                      self.group(0))


class Pattern:
    """A compiled regular expression, modelled after ``re.Pattern``.

    The pattern string is parsed exactly once at construction; the
    resulting AST is reused for every match operation.
    """

    def __init__(self, pattern):
        self.pattern = pattern
        self.ast, self.groups = parse(pattern)

    # -- core matching ----------------------------------------------------

    def _run_at(self, string, start, require_end=False):
        result = engine.run(self.ast, self.groups, string, start,
                            require_end=require_end)
        if result is None:
            return None
        _, spans = result
        return Match(self, string, spans)

    def match(self, string, pos=0):
        """Try to match at the beginning of *string* (or at *pos*)."""
        if pos < 0 or pos > len(string):
            return None
        return self._run_at(string, pos)

    def fullmatch(self, string, pos=0):
        """Match only if the whole string (from *pos*) is consumed."""
        if pos < 0 or pos > len(string):
            return None
        return self._run_at(string, pos, require_end=True)

    def search(self, string, pos=0):
        """Scan *string* for the first location where the pattern matches."""
        pos = max(pos, 0)
        for start in range(pos, len(string) + 1):
            m = self._run_at(string, start)
            if m is not None:
                return m
        return None

    # -- iteration ----------------------------------------------------------

    def finditer(self, string):
        """Yield Match objects for all non-overlapping matches."""
        pos = 0
        while pos <= len(string):
            m = self.search(string, pos)
            if m is None:
                return
            yield m
            # After an empty match, advance one character to avoid
            # looping forever on the same position.
            pos = m.end() if m.end() > m.start() else m.end() + 1

    def findall(self, string):
        """Return all non-overlapping matches.

        Like ``re.findall``: with no groups, a list of matched strings;
        with one group, a list of that group's contents; with several
        groups, a list of tuples.
        """
        matches = self.finditer(string)
        if self.groups == 0:
            return [m.group(0) for m in matches]
        if self.groups == 1:
            return [m.group(1) if m.group(1) is not None else ""
                    for m in matches]
        return [tuple(g if g is not None else "" for g in m.groups())
                for m in matches]

    def __repr__(self):
        return "regexlab.compile(%r)" % self.pattern


# -- module-level API -------------------------------------------------------


def compile(pattern):
    """Compile *pattern* into a reusable :class:`Pattern` object."""
    if isinstance(pattern, Pattern):
        return pattern
    cached = _CACHE.get(pattern)
    if cached is not None:
        return cached
    compiled = Pattern(pattern)
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[pattern] = compiled
    return compiled


def purge():
    """Clear the pattern cache."""
    _CACHE.clear()


def match(pattern, string):
    """Compile *pattern* and try to match at the start of *string*."""
    return compile(pattern).match(string)


def search(pattern, string):
    """Compile *pattern* and find the first match inside *string*."""
    return compile(pattern).search(string)


def fullmatch(pattern, string):
    """Compile *pattern* and require the whole *string* to match."""
    return compile(pattern).fullmatch(string)


def findall(pattern, string):
    """Compile *pattern* and return all non-overlapping matches."""
    return compile(pattern).findall(string)


def finditer(pattern, string):
    """Compile *pattern* and iterate over all non-overlapping matches."""
    return compile(pattern).finditer(string)
