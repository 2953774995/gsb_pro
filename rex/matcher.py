"""Backtracking matching engine.

The matcher is a set of generators: ``_match(node, pos, caps, ctx)`` lazily
yields ``(end_pos, caps)`` pairs in backtracking preference order (greedy
quantifiers yield their longest matches first, lazy ones the shortest,
alternation tries branches left to right).

``caps`` is an immutable tuple of capture slots; slot 0 is unused (the
whole-match span is tracked separately), slots 1..N correspond to capture
groups in left-parenthesis order.

Two potentially unbounded recursions are implemented with explicit stacks
instead of Python recursion so that long inputs cannot overflow the
interpreter stack:

* ``_repeat``    -- iteration count is bounded by the input length
* ``_match_concat`` -- sequence length is bounded by the pattern length

Every generator step is charged against a per-operation step budget
(``Context.tick``); exceeding it raises :class:`RegexTimeoutError`, which
guards against catastrophic backtracking such as ``(a+)+$``.
"""
from . import ast_nodes as ast
from .errors import RegexTimeoutError

# Compile flags (bit values mirror the stdlib `re` module).
IGNORECASE = 0x2
MULTILINE = 0x8


class Context:
    """Per-operation matching state: input text, flags and step budget."""

    __slots__ = ("text", "flags", "max_steps", "steps")

    def __init__(self, text, flags, max_steps):
        self.text = text
        self.flags = flags
        self.max_steps = max_steps
        self.steps = 0

    def tick(self):
        self.steps += 1
        if self.steps > self.max_steps:
            raise RegexTimeoutError(
                "match aborted: exceeded the step limit of {} "
                "(possible catastrophic backtracking)".format(self.max_steps))


def _class_matches(code, ch):
    if code == "d" or code == "D":
        res = "0" <= ch <= "9"
    elif code == "w" or code == "W":
        res = ch.isalnum() or ch == "_"
    else:  # s / S
        res = ch in " \t\n\r\f\v"
    return res if code.islower() else not res


def _in_char_class(node, ch, icase):
    for item in node.items:
        kind = item[0]
        if kind == "class":
            if _class_matches(item[1], ch):
                return True
        elif kind == "char":
            if ch == item[1]:
                return True
            if icase and (ch.lower() == item[1] or ch.upper() == item[1]):
                return True
        else:  # "range"
            lo, hi = item[1], item[2]
            if lo <= ch <= hi:
                return True
            if icase and (lo <= ch.lower() <= hi or lo <= ch.upper() <= hi):
                return True
    return False


def _anchor_ok(kind, pos, ctx):
    text = ctx.text
    if kind == "start":
        if pos == 0:
            return True
        return bool(ctx.flags & MULTILINE) and text[pos - 1] == "\n"
    # "end"
    if pos == len(text):
        return True
    return bool(ctx.flags & MULTILINE) and text[pos] == "\n"


def _set_cap(caps, slot, value):
    lst = list(caps)
    lst[slot] = value
    return tuple(lst)


def _match(node, pos, caps, ctx):
    """Yield (end_pos, caps) for every way ``node`` can match at ``pos``."""
    ctx.tick()
    if isinstance(node, ast.Literal):
        text = ctx.text
        if pos < len(text):
            ch = text[pos]
            if ch == node.char or (
                    ctx.flags & IGNORECASE
                    and ch.lower() == node.char.lower()):
                yield pos + 1, caps
    elif isinstance(node, ast.Dot):
        if pos < len(ctx.text) and ctx.text[pos] != "\n":
            yield pos + 1, caps
    elif isinstance(node, ast.Anchor):
        if _anchor_ok(node.kind, pos, ctx):
            yield pos, caps
    elif isinstance(node, ast.CharClass):
        if pos < len(ctx.text):
            matched = _in_char_class(
                node, ctx.text[pos], bool(ctx.flags & IGNORECASE))
            if matched != node.negated:
                yield pos + 1, caps
    elif isinstance(node, ast.Concat):
        for end, c in _match_concat(node.children, pos, caps, ctx):
            yield end, c
    elif isinstance(node, ast.Alt):
        for branch in node.branches:
            for end, c in _match(branch, pos, caps, ctx):
                yield end, c
    elif isinstance(node, ast.Group):
        for end, c in _match(node.child, pos, caps, ctx):
            if node.slot is not None:
                c = _set_cap(c, node.slot, (pos, end))
            yield end, c
    elif isinstance(node, ast.Repeat):
        for end, c in _repeat(node, pos, caps, ctx):
            yield end, c
    else:  # pragma: no cover - defensive
        raise AssertionError("unknown AST node {!r}".format(node))


def _match_concat(children, pos, caps, ctx):
    """Match a sequence of nodes using an explicit backtracking stack."""
    n = len(children)
    iters = [None] * n
    poses = [0] * (n + 1)
    caps_at = [None] * (n + 1)
    poses[0] = pos
    caps_at[0] = caps
    i = 0
    while i >= 0:
        ctx.tick()
        if i == n:
            yield poses[n], caps_at[n]
            i -= 1
            continue
        if iters[i] is None:
            iters[i] = _match(children[i], poses[i], caps_at[i], ctx)
        advanced = False
        for end, c in iters[i]:
            poses[i + 1] = end
            caps_at[i + 1] = c
            i += 1
            advanced = True
            break
        if not advanced:
            iters[i] = None
            i -= 1


def _repeat(node, pos, caps, ctx):
    """Match ``node.child`` between ``node.min`` and ``node.max`` times.

    Implemented with an explicit stack of frames
    ``[pos, caps, count, child_iterator, entered]`` so that the iteration
    count (bounded by the remaining input length) cannot overflow the
    Python call stack.  Greedy repeats try to consume more before yielding
    the exit position; lazy repeats yield the exit position first.
    """
    greedy = node.greedy
    lo = node.min
    hi = node.max  # None = unbounded
    stack = [[pos, caps, 0, None, False]]
    while stack:
        ctx.tick()
        frame = stack[-1]
        fpos, fcaps, count, it, entered = frame
        if not entered:
            frame[4] = True
            if not greedy and count >= lo:
                yield fpos, fcaps
            if hi is None or count < hi:
                frame[3] = _match(node.child, fpos, fcaps, ctx)
                continue
            # No further iteration allowed: exit immediately.
            stack.pop()
            if greedy and count >= lo:
                yield fpos, fcaps
            continue
        # Frame already entered: pull the next way the child can match.
        progressed = False
        for end, c in it:
            if end == fpos:
                continue  # empty iteration: no progress, try next way
            stack.append([end, c, count + 1, None, False])
            progressed = True
            break
        if not progressed:
            stack.pop()
            if greedy and count >= lo:
                yield fpos, fcaps
