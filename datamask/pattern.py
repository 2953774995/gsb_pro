"""Public Pattern / Match API and the compile() entry point."""

from .compiler import compile_ast
from .engine import StepCounter, run
from .options import DEFAULT_MAX_STEPS, MULTILINE
from .parser import parse


class Match:
    """The result of a successful match.

    Mirrors the stdlib ``re.Match`` surface we support:
    group()/groups()/span()/start()/end().
    """

    __slots__ = ("re", "string", "_regs")

    def __init__(self, pattern, string, regs):
        self.re = pattern
        self.string = string
        self._regs = regs

    # -- group access ---------------------------------------------------
    def _index(self, g):
        if isinstance(g, str):
            try:
                return self.re.groupindex[g]
            except KeyError:
                raise IndexError("no such group: %r" % g) from None
        if isinstance(g, int) and 0 <= g <= self.re.groups:
            return g
        raise IndexError("no such group: %r" % (g,))

    def _group(self, g):
        i = self._index(g)
        s = self._regs[2 * i]
        if s < 0:
            return None
        return self.string[s:self._regs[2 * i + 1]]

    def group(self, *args):
        """group(0) is the whole match; group(n)/group(name) pick one."""
        if not args:
            return self._group(0)
        if len(args) == 1:
            return self._group(args[0])
        return tuple(self._group(a) for a in args)

    def groups(self, default=None):
        """Tuple of all capture groups 1..N (default for non-matching)."""
        out = []
        for i in range(1, self.re.groups + 1):
            v = self._group(i)
            out.append(default if v is None else v)
        return tuple(out)

    def span(self, g=0):
        i = self._index(g)
        return (self._regs[2 * i], self._regs[2 * i + 1])

    def start(self, g=0):
        return self.span(g)[0]

    def end(self, g=0):
        return self.span(g)[1]

    def __getitem__(self, g):
        return self._group(g)

    def __repr__(self):
        return "<datamask.Match span=%r match=%r>" % (self.span(), self.group(0))


class Pattern:
    """A compiled pattern.  Create via datamask.compile()."""

    def __init__(self, source, flags, prog, ngroups, groupindex, nregs,
                 max_steps):
        self.pattern = source
        self.flags = flags
        self.groups = ngroups
        self.groupindex = groupindex
        self.max_steps = max_steps
        self._prog = prog
        self._nregs = nregs
        # ^ anchored patterns (without MULTILINE) only need one attempt.
        self._anchored = (
            prog[0][0] == "bol" and not (flags & MULTILINE)
        )

    # -- core ------------------------------------------------------------
    def _attempt(self, string, start, counter, require_end):
        regs = run(self._prog, string, start, self.flags, counter,
                   self._nregs, require_end)
        if regs is None:
            return None
        return Match(self, string, regs)

    def _search_from(self, string, pos, counter):
        n = len(string)
        start = pos
        while start <= n:
            m = self._attempt(string, start, counter, require_end=False)
            if m is not None:
                return m
            start += 1
            if self._anchored:
                break
        return None

    # -- public API -------------------------------------------------------
    def search(self, string, pos=0):
        """Scan *string* for the first match, or return None."""
        return self._search_from(string, pos, StepCounter(self.max_steps))

    def match(self, string):
        """Match anchored at the beginning of *string* (not fullmatch)."""
        return self._attempt(string, 0, StepCounter(self.max_steps), False)

    def fullmatch(self, string):
        """Match only if the whole string is consumed."""
        return self._attempt(string, 0, StepCounter(self.max_steps), True)

    def finditer(self, string):
        """Lazily yield Match objects for all non-overlapping matches."""
        pos = 0
        n = len(string)
        while pos <= n:
            m = self._search_from(string, pos, StepCounter(self.max_steps))
            if m is None:
                return
            yield m
            if m.end() == m.start():
                pos = m.end() + 1  # empty match: make progress
            else:
                pos = m.end()

    def findall(self, string):
        """All matches: strings (0 groups), group (1 group) or tuples."""
        if self.groups == 0:
            return [m.group(0) for m in self.finditer(string)]
        if self.groups == 1:
            return [m.group(1) for m in self.finditer(string)]
        return [m.groups() for m in self.finditer(string)]

    def __repr__(self):
        return "datamask.compile(%r, flags=%d)" % (self.pattern, self.flags)


def compile(pattern, flags=0, max_steps=DEFAULT_MAX_STEPS):
    """Compile *pattern* into a Pattern object.

    flags:      IGNORECASE and/or MULTILINE (bitwise-or).
    max_steps:  per-match step budget; PatternTimeoutError when exceeded.
    """
    ast, ngroups, group_names = parse(pattern)
    prog, nregs = compile_ast(ast, flags, ngroups)
    return Pattern(pattern, flags, prog, ngroups, dict(group_names),
                   nregs, max_steps)
