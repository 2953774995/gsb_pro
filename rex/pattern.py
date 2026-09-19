"""Compilation options, the Pattern API and match-result objects."""
from .errors import RegexError
from .matcher import (Context, IGNORECASE, MULTILINE, _match)
from .parser import Parser

DEFAULT_MAX_STEPS = 100_000_000

_ALLOWED_FLAGS = IGNORECASE | MULTILINE


def compile(pattern, flags=0, max_steps=DEFAULT_MAX_STEPS):
    """Compile ``pattern`` into a :class:`Pattern`.

    ``flags`` is a bitmask of ``IGNORECASE`` / ``MULTILINE``.
    ``max_steps`` caps the work of any single match operation; exceeding
    it raises :class:`RegexTimeoutError`.
    """
    if flags & ~_ALLOWED_FLAGS:
        raise RegexError("unknown flag(s): 0x{:x}".format(
            flags & ~_ALLOWED_FLAGS))
    if max_steps <= 0:
        raise RegexError("max_steps must be a positive integer")
    parser = Parser(pattern)
    root = parser.parse()
    return Pattern(pattern, flags, root, parser, max_steps)


class Pattern:
    """A compiled regular expression."""

    def __init__(self, pattern, flags, root, parser, max_steps):
        self.pattern = pattern
        self.flags = flags
        self._ast = root
        self._nslots = parser.slots
        self._num2slot = dict(parser.num2slot)
        self._name2slot = dict(parser.names)
        #: number of numbered (unnamed) capture groups
        self.groups = parser.group_count
        #: mapping of named groups to internal capture slots
        self.groupindex = dict(parser.names)
        self.max_steps = max_steps

    # -- internal helpers --------------------------------------------------
    def _empty_caps(self):
        return (None,) * (self._nslots + 1)

    def _iter_at(self, text, start, ctx):
        return _match(self._ast, start, self._empty_caps(), ctx)

    def _search_from(self, text, pos):
        ctx = Context(text, self.flags, self.max_steps)
        for start in range(pos, len(text) + 1):
            for end, caps in self._iter_at(text, start, ctx):
                return Match(self, text, start, end, caps)
        return None

    # -- public API --------------------------------------------------------
    def search(self, text, pos=0):
        """Scan ``text`` for the first location where the pattern matches."""
        return self._search_from(text, pos)

    def match(self, text, pos=0):
        """Match the pattern anchored at ``pos`` (default: start of text)."""
        ctx = Context(text, self.flags, self.max_steps)
        for end, caps in self._iter_at(text, pos, ctx):
            return Match(self, text, pos, end, caps)
        return None

    def fullmatch(self, text, pos=0):
        """Match only if the pattern covers the whole text from ``pos``."""
        ctx = Context(text, self.flags, self.max_steps)
        for end, caps in self._iter_at(text, pos, ctx):
            if end == len(text):
                return Match(self, text, pos, end, caps)
        return None

    def finditer(self, text):
        """Lazily yield :class:`Match` objects for all non-overlapping
        matches, left to right.  Empty matches are allowed; after an empty
        match the scan resumes one character later."""
        pos = 0
        n = len(text)
        while pos <= n:
            m = self._search_from(text, pos)
            if m is None:
                return
            yield m
            pos = m.end() if m.end() > m.start() else m.end() + 1

    def findall(self, text):
        """Return all non-overlapping matches as a list.

        With no numbered groups the whole match strings are returned; with
        exactly one numbered group, that group's strings; otherwise tuples
        of the numbered groups (mirroring ``re.findall``).
        """
        out = []
        for m in self.finditer(text):
            if self.groups == 0:
                out.append(m.group(0))
            elif self.groups == 1:
                out.append(m.group(1))
            else:
                out.append(m.groups())
        return out

    def __repr__(self):
        return "rex.compile({!r}, flags={})".format(self.pattern, self.flags)


class Match:
    """The result of a successful match."""

    __slots__ = ("re", "string", "pos", "_start", "_end", "_caps")

    def __init__(self, pattern, text, start, end, caps):
        self.re = pattern
        self.string = text
        self.pos = start
        self._start = start
        self._end = end
        self._caps = caps

    # -- group access ------------------------------------------------------
    def _slot(self, key):
        if isinstance(key, str):
            try:
                return self.re._name2slot[key]
            except KeyError:
                raise IndexError("unknown group name {!r}".format(key))
        if not isinstance(key, int):
            raise TypeError("group indices must be integers or names")
        if key == 0:
            return 0
        if 1 <= key <= self.re.groups:
            return self.re._num2slot[key]
        raise IndexError("no such group: {}".format(key))

    def group(self, *keys):
        """Return one or more groups of the match.

        ``group()`` / ``group(0)`` is the whole match; ``group(n)`` the
        n-th numbered group; ``group(name)`` a named group.  Groups that
        did not participate in the match return None.
        """
        if not keys:
            keys = (0,)
        if len(keys) == 1:
            return self._group1(keys[0])
        return tuple(self._group1(k) for k in keys)

    def _group1(self, key):
        if key == 0:
            return self.string[self._start:self._end]
        span = self._caps[self._slot(key)]
        if span is None:
            return None
        return self.string[span[0]:span[1]]

    def groups(self, default=None):
        """Return a tuple of all numbered groups (None -> ``default``)."""
        out = []
        for i in range(1, self.re.groups + 1):
            value = self._group1(i)
            out.append(default if value is None else value)
        return tuple(out)

    def groupdict(self, default=None):
        """Return a dict of all named groups (None -> ``default``)."""
        out = {}
        for name in self.re._name2slot:
            value = self._group1(name)
            out[name] = default if value is None else value
        return out

    # -- positions ---------------------------------------------------------
    def span(self, key=0):
        """Return ``(start, end)`` of the whole match or a group.

        Non-participating groups return ``(-1, -1)``."""
        if key == 0:
            return (self._start, self._end)
        span = self._caps[self._slot(key)]
        return (-1, -1) if span is None else span

    def start(self, key=0):
        return self.span(key)[0]

    def end(self, key=0):
        return self.span(key)[1]

    def __repr__(self):
        return "<rex.Match span={} match={!r}>".format(
            self.span(), self.group())
