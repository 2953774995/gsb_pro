"""Public API: compile(), Pattern and Match."""

import sys

from . import matcher as _matcher
from .errors import RegexError
from .flags import IGNORECASE, MULTILINE  # noqa: F401  (re-exported)
from .parser import parse

#: Default per-match step budget (guards against catastrophic backtracking).
DEFAULT_STEP_LIMIT = _matcher.DEFAULT_STEP_LIMIT

# The recursive matcher needs headroom proportional to the input length;
# this caps how far we are willing to raise the interpreter limit.
_MAX_RECURSION_LIMIT = 100_000


def compile(pattern, flags=0, step_limit=DEFAULT_STEP_LIMIT):
    """Compile *pattern* into a :class:`Pattern` object."""
    return Pattern(pattern, flags, step_limit=step_limit)


class Pattern:
    """A compiled regular expression."""

    def __init__(self, pattern, flags=0, step_limit=DEFAULT_STEP_LIMIT):
        self.pattern = pattern
        self.flags = flags
        self.step_limit = step_limit
        self.ast, self.groups, self.groupindex, self._slots = parse(pattern)

    # -- internal helpers -------------------------------------------------

    def _check_string(self, string):
        if not isinstance(string, str):
            raise TypeError(
                "expected string for matching, got %s" % type(string).__name__
            )

    def _search(self, string, pos, endpos):
        """Run the engine; return (caps, start, end) or None."""
        limit_needed = min(_MAX_RECURSION_LIMIT, 16 * (len(string) + 64))
        old_limit = sys.getrecursionlimit()
        if limit_needed > old_limit:
            sys.setrecursionlimit(limit_needed)
        try:
            result = _matcher.search(
                self.ast, self._slots, string, pos, endpos,
                self.flags, self.step_limit,
            )
        except RecursionError:
            raise RegexError(
                "match aborted: maximum recursion depth exceeded "
                "(input too long for the backtracking matcher)"
            )
        finally:
            if sys.getrecursionlimit() != old_limit:
                sys.setrecursionlimit(old_limit)
        if result is None:
            return None
        state, end = result
        return state.caps, state.caps[0][0], end

    # -- public API --------------------------------------------------------

    def search(self, string, pos=0, endpos=None):
        """Scan *string* for the first location where the pattern matches."""
        self._check_string(string)
        pos, endpos = self._bounds(string, pos, endpos)
        found = self._search(string, pos, endpos)
        if found is None:
            return None
        caps, start, end = found
        return Match(self, string, pos, endpos, caps)

    def match(self, string, pos=0, endpos=None):
        """Match only at the beginning of *string* (or at *pos*)."""
        self._check_string(string)
        pos, endpos = self._bounds(string, pos, endpos)
        found = self._search(string, pos, endpos)
        if found is None:
            return None
        caps, start, end = found
        if start != pos:
            return None
        return Match(self, string, pos, endpos, caps)

    def fullmatch(self, string, pos=0, endpos=None):
        """Match only if the pattern covers the whole string."""
        self._check_string(string)
        pos, endpos = self._bounds(string, pos, endpos)
        found = self._search(string, pos, endpos)
        if found is None:
            return None
        caps, start, end = found
        if start != pos or end != endpos:
            return None
        return Match(self, string, pos, endpos, caps)

    def finditer(self, string, pos=0, endpos=None):
        """Yield Match objects for all non-overlapping matches."""
        self._check_string(string)
        pos, endpos = self._bounds(string, pos, endpos)
        cursor = pos
        while cursor <= endpos:
            found = self._search(string, cursor, endpos)
            if found is None:
                return
            caps, start, end = found
            yield Match(self, string, pos, endpos, caps)
            # Advance past the match; an empty match must make progress.
            cursor = end + 1 if end == start else end

    def findall(self, string, pos=0, endpos=None):
        """Return all non-overlapping matches as strings or tuples.

        Mirrors re.findall: with no groups the whole matches are
        returned, with one group the group contents, and with several
        groups tuples of group contents.
        """
        result = []
        for m in self.finditer(string, pos, endpos):
            if self.groups == 0:
                result.append(m.group(0))
            elif self.groups == 1:
                result.append(m.group(1))
            else:
                result.append(m.groups())
        return result

    @staticmethod
    def _bounds(string, pos, endpos):
        n = len(string)
        if endpos is None:
            endpos = n
        pos = max(0, min(pos, n))
        endpos = max(0, min(endpos, n))
        return pos, endpos

    def __repr__(self):
        return "rex.compile(%r, flags=%r)" % (self.pattern, self.flags)


class Match:
    """The result of a successful match."""

    __slots__ = ("re", "string", "pos", "endpos", "_caps")

    def __init__(self, pattern, string, pos, endpos, caps):
        self.re = pattern
        self.string = string
        self.pos = pos
        self.endpos = endpos
        self._caps = caps

    # -- group access ------------------------------------------------------

    def _group_index(self, key):
        if isinstance(key, str):
            if key not in self.re.groupindex:
                raise IndexError("unknown group name %r" % key)
            return self.re.groupindex[key]
        if isinstance(key, int):
            if 0 <= key <= self.re.groups:
                return key
            raise IndexError("no such group: %r" % key)
        raise TypeError("group indices must be integers or strings")

    def group(self, *keys):
        """Return one or more subgroups of the match."""
        if not keys:
            keys = (0,)
        values = []
        for key in keys:
            idx = self._group_index(key)
            span = self._caps[idx]
            if span is None:
                values.append(None)
            else:
                values.append(self.string[span[0]:span[1]])
        if len(values) == 1:
            return values[0]
        return tuple(values)

    def groups(self, default=None):
        """Return a tuple of all capture groups (1..n)."""
        out = []
        for idx in range(1, self.re.groups + 1):
            span = self._caps[idx]
            if span is None:
                out.append(default)
            else:
                out.append(self.string[span[0]:span[1]])
        return tuple(out)

    def groupdict(self, default=None):
        """Return a dict mapping named groups to their matches."""
        out = {}
        for name, idx in self.re.groupindex.items():
            span = self._caps[idx]
            out[name] = default if span is None else self.string[span[0]:span[1]]
        return out

    # -- spans -------------------------------------------------------------

    def span(self, key=0):
        """Return (start, end) of the match (or of a group)."""
        idx = self._group_index(key)
        span = self._caps[idx]
        if span is None:
            return (-1, -1)
        return span

    def start(self, key=0):
        return self.span(key)[0]

    def end(self, key=0):
        return self.span(key)[1]

    def __repr__(self):
        return "<rex.Match span=%r match=%r>" % (self.span(), self.group(0))
