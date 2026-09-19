"""Backtracking matcher.

The matcher walks the AST with explicit recursive generator functions.
Each ``_match_*(node, pos, state)`` is a generator that yields every
position at which ``node`` can finish, in preference order (greedy
quantifiers try longer runs first, lazy ones shorter runs first,
alternation tries branches left to right).

A shared :class:`_State` object carries the text, compilation flags,
capture slots and the remaining step budget.  Every elementary action
(character test, anchor test, backtracking choice point) consumes one
step; when the budget is exhausted a :class:`RegexTimeoutError` is
raised, which guarantees that catastrophic-backtracking patterns such
as ``(a+)+$`` terminate instead of hanging.
"""

from . import ast
from .errors import RegexTimeoutError
from .flags import IGNORECASE, MULTILINE

DEFAULT_STEP_LIMIT = 100_000_000

_DIGITS = "0123456789"
_WORD = ("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
         "0123456789_")
_SPACE = " \t\n\r\f\v"

_CLASS_SETS = {
    "d": _DIGITS,
    "w": _WORD,
    "s": _SPACE,
}


def _fold(text):
    """Case folding used for IGNORECASE."""
    return text.casefold()


class _State:
    __slots__ = ("text", "endpos", "folded", "flags", "steps", "limit", "caps")

    def __init__(self, text, endpos, flags, ngroups, limit):
        self.text = text
        self.endpos = endpos
        self.folded = _fold(text) if flags & IGNORECASE else None
        self.flags = flags
        self.steps = 0
        self.limit = limit
        self.caps = [None] * (ngroups + 1)

    def tick(self):
        self.steps += 1
        if self.steps > self.limit:
            raise RegexTimeoutError(self.steps, self.limit)


class _Matcher:
    def __init__(self, state):
        self.state = state

    # -- public ----------------------------------------------------------

    def run(self, node, pos):
        """Yield every end position reachable from *pos*."""
        yield from self._match(node, pos)

    # -- dispatch ---------------------------------------------------------

    def _match(self, node, pos):
        handler = self._handlers[type(node)]
        yield from handler(self, node, pos)

    # -- leaf nodes -------------------------------------------------------

    def _match_literal(self, node, pos):
        st = self.state
        st.tick()
        if st.folded is not None:
            if pos < st.endpos and st.folded[pos] == _fold(node.char):
                yield pos + 1
        elif pos < st.endpos and st.text[pos] == node.char:
            yield pos + 1

    def _match_dot(self, node, pos):
        st = self.state
        st.tick()
        if pos < st.endpos and st.text[pos] != "\n":
            yield pos + 1

    def _match_class_escape(self, node, pos):
        st = self.state
        st.tick()
        if pos < st.endpos and self._class_escape_test(node.name, st.text[pos]):
            yield pos + 1

    def _match_char_class(self, node, pos):
        st = self.state
        st.tick()
        if pos >= st.endpos:
            return
        ch = st.text[pos]
        if st.folded is not None:
            ch = _fold(ch)
        if self._class_test(node, ch) != node.negated:
            yield pos + 1

    def _class_test(self, node, ch):
        for item in node.items:
            kind = item[0]
            if kind == "lit":
                cand = item[1]
                if self.state.folded is not None:
                    cand = _fold(cand)
                if ch == cand:
                    return True
            elif kind == "range":
                lo, hi = item[1], item[2]
                if self.state.folded is not None:
                    lo, hi = _fold(lo), _fold(hi)
                if lo <= ch <= hi:
                    return True
            else:  # "class"
                if self._class_escape_test(item[1], ch):
                    return True
        return False

    @staticmethod
    def _class_escape_test(name, ch):
        base = _CLASS_SETS[name.lower()]
        found = ch in base
        return found if name.islower() else not found

    def _match_anchor(self, node, pos):
        st = self.state
        st.tick()
        text = st.text
        if node.kind == "start":
            if pos == 0:
                yield pos
            elif st.flags & MULTILINE and text[pos - 1] == "\n":
                yield pos
        else:  # "end"
            if pos == st.endpos:
                yield pos
            elif st.flags & MULTILINE and pos < st.endpos and text[pos] == "\n":
                yield pos

    # -- composite nodes --------------------------------------------------

    def _match_concat(self, node, pos):
        yield from self._match_seq(node.children, 0, pos)

    def _match_seq(self, nodes, index, pos):
        if index == len(nodes):
            yield pos
            return
        for mid in self._match(nodes[index], pos):
            yield from self._match_seq(nodes, index + 1, mid)

    def _match_alternate(self, node, pos):
        for branch in node.branches:
            yield from self._match(branch, pos)

    def _match_group(self, node, pos):
        st = self.state
        if node.index is None:
            yield from self._match(node.child, pos)
            return
        idx = node.index
        saved = st.caps[idx]
        for end in self._match(node.child, pos):
            st.caps[idx] = (pos, end)
            yield end
        st.caps[idx] = saved

    def _match_repeat(self, node, pos):
        yield from self._rep(node, pos, 0)

    def _rep(self, node, pos, count):
        st = self.state
        st.tick()
        can_more = node.max is None or count < node.max
        if node.greedy:
            if can_more:
                for end in self._match(node.child, pos):
                    if end == pos:
                        # Zero-width iteration: further iterations would
                        # also match empty, so jump straight to the
                        # minimum count (if not yet reached) and stop
                        # looping to avoid infinite recursion.
                        if count < node.min:
                            yield end
                        continue
                    yield from self._rep(node, end, count + 1)
            if count >= node.min:
                yield pos
        else:
            if count >= node.min:
                yield pos
            if can_more:
                for end in self._match(node.child, pos):
                    if end == pos:
                        if count < node.min:
                            yield end
                        continue
                    yield from self._rep(node, end, count + 1)


_Matcher._handlers = {
    ast.Literal: _Matcher._match_literal,
    ast.Dot: _Matcher._match_dot,
    ast.CharClass: _Matcher._match_char_class,
    ast.ClassEscape: _Matcher._match_class_escape,
    ast.Anchor: _Matcher._match_anchor,
    ast.Concat: _Matcher._match_concat,
    ast.Alternate: _Matcher._match_alternate,
    ast.Group: _Matcher._match_group,
    ast.Repeat: _Matcher._match_repeat,
}


def search(root, ngroups, text, pos, endpos, flags, limit):
    """Find the first match of *root* in ``text[pos:endpos]``.

    Returns ``(state, end)`` on success (``state.caps`` holds the capture
    spans) or ``None`` when no match exists.
    """
    state = _State(text, endpos, flags, ngroups, limit)
    matcher = _Matcher(state)
    start = pos
    while start <= endpos:
        state.caps = [None] * (ngroups + 1)
        for end in matcher.run(root, start):
            state.caps[0] = (start, end)
            return state, end
        start += 1
    return None
