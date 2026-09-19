"""Backtracking virtual machine for the rex regex engine.

The AST produced by :mod:`rex.parser` is compiled to a flat list of
instructions executed by an explicit-stack backtracking interpreter.  Using
an explicit Python list as the choice stack (instead of Python call frames)
keeps the interpreter safe from Python recursion-depth failures on long
inputs and makes the global step budget cheap to enforce.

Instructions are tuples ``(opcode, *args)``:

  ("char", ch)            consume one character equal to ch
  ("any",)                consume any character except newline
  ("class", ClassMatcher) consume one character accepted by the class
  ("anchor", kind)        zero-width ^ / $ assertion
  ("split", a, b)         continue at a; remember b as an alternative
  ("jmp", target)         unconditional jump
  ("gstart", slot)        record capture start (restored on backtrack)
  ("gend", slot)          record capture end (restored on backtrack)
  ("match",)              report overall success
"""

from . import ast_nodes as ast
from .errors import RegexError, RegexTimeoutError
from . import flags as _flags

# Opcodes (also used by the API layer and tests).
CHAR = "char"
ANY = "any"
CLS = "class"
ANCHOR = "anchor"
SPLIT = "split"
JMP = "jmp"
GSTART = "gstart"
GEND = "gend"
MATCH_OP = "match"


class ClassMatcher(object):
    """Pre-resolved membership test for a character class."""

    __slots__ = ("negated", "explicit", "predicates")

    def __init__(self, negated, items, ignorecase=False):
        self.negated = negated
        explicit = set()
        predicates = []
        for item in items:
            if item[0] == "char":
                self._add_char(explicit, item[1], ignorecase)
            elif item[0] == "range":
                lo, hi = item[1], item[2]
                for code in range(ord(lo), ord(hi) + 1):
                    self._add_char(explicit, chr(code), ignorecase)
            else:
                predicates.append(_PREDICATES[item[1]])
        self.explicit = frozenset(explicit)
        self.predicates = tuple(predicates)

    @staticmethod
    def _add_char(explicit, ch, ignorecase):
        explicit.add(ch)
        if ignorecase:
            folded = ch.casefold()
            if len(folded) == 1:
                explicit.add(folded)
                upper = folded.upper()
                if len(upper) == 1:
                    explicit.add(upper)

    def matches(self, ch):
        hit = ch in self.explicit or any(pred(ch) for pred in self.predicates)
        return not hit if self.negated else hit


def _is_digit(ch):
    return ch.isdecimal()


def _is_space(ch):
    return ch in " \t\n\r\f\v" or ch.isspace()


_PREDICATES = {
    "d": _is_digit,
    "D": lambda ch: not _is_digit(ch),
    "w": lambda ch: ch == "_" or ch.isalnum(),
    "W": lambda ch: not (ch == "_" or ch.isalnum()),
    "s": _is_space,
    "S": lambda ch: not _is_space(ch),
}


def anchor_ok(kind, text, pos, multiline):
    if kind == "start":
        if pos == 0:
            return True
        if multiline:
            return text[pos - 1] == "\n"
        return False
    # kind == "end": end of text, or immediately before a newline.  In the
    # default mode only the single trailing newline qualifies; in multiline
    # mode every line ending does.
    if pos == len(text):
        return True
    if text[pos] != "\n":
        return False
    if multiline:
        return True
    return pos == len(text) - 1


class Program(object):
    """A compiled pattern ready for VM execution."""

    __slots__ = ("code", "group_count", "names", "num_count", "flags")

    def __init__(self, code, group_count, names, num_count, flags):
        self.code = code
        self.group_count = group_count
        self.names = names
        self.num_count = num_count
        self.flags = flags


class Compiler(object):
    def __init__(self, flags=0):
        self.code = []
        self.flags = flags
        self.ignorecase = bool(flags & _flags.IGNORECASE)
        self.multiline = bool(flags & _flags.MULTILINE)

    def emit(self, ins):
        self.code.append(ins)
        return len(self.code) - 1

    def compile(self, tree, meta):
        self._node(tree)
        self.emit((MATCH_OP,))
        return Program(
            self.code, meta["group_count"], meta["names"], meta["num_count"], self.flags
        )

    # -- node compilation ---------------------------------------------------

    def _node(self, node):
        if isinstance(node, ast.Concat):
            for child in node.nodes:
                self._node(child)
        elif isinstance(node, ast.Alt):
            jmp_patches = []
            for idx, branch in enumerate(node.branches):
                if idx == len(node.branches) - 1:
                    self._node(branch)
                    break
                split_idx = self.emit(None)
                self._node(branch)
                jmp_patches.append(self.emit(None))
                next_idx = len(self.code)
                self.code[split_idx] = (SPLIT, split_idx + 1, next_idx)
            for idx in jmp_patches:
                self.code[idx] = (JMP, len(self.code))
        elif isinstance(node, ast.Repeat):
            self._repeat(node)
        elif isinstance(node, ast.Group):
            if node.slot >= 0:
                self.emit((GSTART, node.slot))
                self._node(node.node)
                self.emit((GEND, node.slot))
            else:
                self._node(node.node)
        elif isinstance(node, ast.Literal):
            self.emit((CHAR, node.char))
        elif isinstance(node, ast.Dot):
            self.emit((ANY,))
        elif isinstance(node, ast.CharClass):
            self.emit((CLS, ClassMatcher(node.negated, node.items, self.ignorecase)))
        elif isinstance(node, ast.Anchor):
            self.emit((ANCHOR, node.kind))
        else:  # pragma: no cover - defensive
            raise RegexError("internal error: unknown AST node %r" % (node,))

    def _repeat(self, node):
        lo = node.min
        hi = node.max
        for _ in range(lo):
            self._node(node.node)
        if hi is None:
            # {lo,} : greedy    L1: split L2, L3 ; L2: body; jmp L1; L3:
            #            nongreedy split L3, L2
            l1 = len(self.code)
            split_idx = self.emit(None)
            self._node(node.node)
            self.emit((JMP, l1))
            l3 = len(self.code)
            if node.greedy:
                self.code[split_idx] = (SPLIT, split_idx + 1, l3)
            else:
                self.code[split_idx] = (SPLIT, l3, split_idx + 1)
        else:
            extra = hi - lo
            if extra > 0:
                # body emitted 'extra' times, each guarded by a split that
                # skips the remaining optional copies.
                split_positions = []
                for _ in range(extra):
                    split_positions.append(self.emit(None))
                    self._node(node.node)
                end = len(self.code)
                for k, sp in enumerate(split_positions):
                    skip = split_positions[k + 1] if k + 1 < extra else end
                    if node.greedy:
                        self.code[sp] = (SPLIT, sp + 1, skip)
                    else:
                        self.code[sp] = (SPLIT, skip, sp + 1)


def compile_tree(tree, meta, flags=0):
    return Compiler(flags).compile(tree, meta)


def attempt_matches(program, text, origin, scan_limit, budget, must_end=None):
    """Yield every successful match of *program* pinned at start *origin*.

    The generator preserves the backtracking choice stack between yielded
    results, so callers can resume a match attempt (used to grow a lazy
    zero-length match at the same position).
    """
    code = program.code
    multiline = bool(program.flags & _flags.MULTILINE)
    ignorecase = bool(program.flags & _flags.IGNORECASE)
    n = len(text)
    nslots = program.group_count
    if scan_limit is None or scan_limit > n:
        scan_limit = n

    pc = 0
    pos = origin
    caps = [None] * (2 * nslots)
    choices = []
    while True:
        if budget[0] <= 0:
            raise RegexTimeoutError(
                "match exceeded the configured step limit of %d instructions" % budget[1]
            )
        budget[0] -= 1
        ins = code[pc]
        op = ins[0]
        if op is CHAR:
            if pos < n and _eq_char(ins[1], text[pos], ignorecase):
                pc += 1
                pos += 1
                continue
        elif op is ANY:
            if pos < n and text[pos] != "\n":
                pc += 1
                pos += 1
                continue
        elif op is CLS:
            if pos < n and ins[1].matches(text[pos]):
                pc += 1
                pos += 1
                continue
        elif op is ANCHOR:
            if anchor_ok(ins[1], text, pos, multiline):
                pc += 1
                continue
        elif op is SPLIT:
            choices.append((ins[2], pos, caps[:]))
            pc = ins[1]
            continue
        elif op is JMP:
            pc = ins[1]
            continue
        elif op is GSTART:
            slot = ins[1]
            caps = caps[:]
            caps[2 * slot] = pos
            pc += 1
            continue
        elif op is GEND:
            slot = ins[1]
            caps = caps[:]
            caps[2 * slot + 1] = pos
            pc += 1
            continue
        else:  # MATCH_OP
            if pos <= scan_limit and (must_end is None or pos == must_end):
                yielded = yield origin, pos, caps
                if yielded is not None:
                    # Explicit close() from the caller: stop enumerating.
                    return
        if choices:
            pc, pos, caps = choices.pop()
            continue
        return


def run_vm(program, text, start, anchored, budget, must_end=None, scan_limit=None):
    """Return the leftmost ``(start, end, caps)`` match, or None.

    * ``anchored`` - pin the pattern to *start*; otherwise every position
      from *start* to ``scan_limit`` is tried, leftmost first.
    * ``must_end`` - require the match to end exactly at this index
      (used for fullmatch).
    * ``budget``   - one-element list carrying the shared instruction budget.
    """
    n = len(text)
    if scan_limit is None or scan_limit > n:
        scan_limit = n
    attempt = start
    while attempt <= scan_limit:
        gen = attempt_matches(program, text, attempt, scan_limit, budget, must_end)
        try:
            return next(gen)
        except StopIteration:
            pass
        finally:
            gen.close()
        if anchored:
            return None
        attempt += 1
    return None


def _eq_char(pattern_char, text_char, ignorecase):
    if pattern_char == text_char:
        return True
    if ignorecase:
        folded_p = pattern_char.casefold()
        if len(folded_p) == 1:
            return folded_p == text_char.casefold()
    return False
