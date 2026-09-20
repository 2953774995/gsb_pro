"""Backtracking VM executing compiled programs.

The VM is iterative (explicit backtrack stack) so deeply nested or
heavily repeated patterns cannot overflow the Python call stack.  Every
executed instruction increments a shared step counter; exceeding the
configured budget raises PatternTimeoutError, which is the defence
against catastrophic backtracking (e.g. "(a+)+$" on long non-matching
input).

Empty-loop protection is compiled in via mark/check instructions: a
star/plus whose body matched the empty string exits the loop instead of
spinning forever.
"""

from .errors import PatternTimeoutError
from .options import MULTILINE


def _is_word(ch):
    return ch == "_" or ch.isalnum()


PREDICATES = {
    "digit": str.isdecimal,
    "space": str.isspace,
    "word": _is_word,
}


def class_match(items, negated, ch):
    """Test *ch* against class items; *negated* inverts the result."""
    ok = False
    for it in items:
        kind = it[0]
        if kind == "range":
            if it[1] <= ch <= it[2]:
                ok = True
                break
        elif kind == "pred":
            if PREDICATES[it[1]](ch):
                ok = True
                break
        else:  # "npred"
            if not PREDICATES[it[1]](ch):
                ok = True
                break
    return ok != negated


class StepCounter:
    """Shared per-operation step budget."""

    __slots__ = ("limit", "count")

    def __init__(self, limit):
        self.limit = limit
        self.count = 0

    def step(self):
        self.count += 1
        if self.count > self.limit:
            raise PatternTimeoutError(self.limit)


def run(prog, text, start, flags, counter, nregs, require_end):
    """Run *prog* against *text* starting exactly at *start*.

    Returns the register array on success (slots 0/1 hold the overall
    span), or None on failure.  *require_end* makes the "match"
    instruction succeed only at end of string (fullmatch semantics).
    """
    multiline = bool(flags & MULTILINE)
    n = len(text)
    regs = [-1] * nregs
    stack = []
    pc = 0
    pos = start
    step = counter.step
    pop = stack.pop

    while True:
        step()
        ins = prog[pc]
        op = ins[0]

        if op == "char":
            if pos < n and text[pos] == ins[1]:
                pos += 1
                pc += 1
                continue
        elif op == "ichar":
            if pos < n and text[pos] in ins[1]:
                pos += 1
                pc += 1
                continue
        elif op == "any":
            if pos < n and text[pos] != "\n":
                pos += 1
                pc += 1
                continue
        elif op == "class":
            if pos < n and class_match(ins[1], ins[2], text[pos]):
                pos += 1
                pc += 1
                continue
        elif op == "bol":
            if pos == 0 or (multiline and text[pos - 1] == "\n"):
                pc += 1
                continue
        elif op == "eol":
            if pos == n or (multiline and text[pos] == "\n"):
                pc += 1
                continue
        elif op == "jmp":
            pc = ins[1]
            continue
        elif op == "split":
            stack.append((ins[2], pos, regs[:]))
            pc = ins[1]
            continue
        elif op == "save" or op == "mark":
            regs[ins[1]] = pos
            pc += 1
            continue
        elif op == "check":
            if regs[ins[1]] == pos:
                pc = ins[2]
            else:
                pc += 1
            continue
        elif op == "match":
            if not require_end or pos == n:
                regs[0] = start
                regs[1] = pos
                return regs
        # failure: backtrack
        if not stack:
            return None
        pc, pos, regs = pop()
