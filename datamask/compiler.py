"""Compiler: AST -> linear instruction program for the backtracking VM.

Instruction set (each instruction is a tuple):

    ("char", ch)            match one exact character
    ("ichar", variants)     match one char, case-insensitively
    ("any",)                match any char except "\\n"
    ("class", items, neg)   match a character class
    ("bol",)                assert beginning of string/line
    ("eol",)                assert end of string/line
    ("jmp", addr)           unconditional jump
    ("split", a, b)         try pc=a first, push b on the backtrack stack
    ("save", slot)          record current pos into register slot
    ("mark", slot)          record pos for empty-loop detection
    ("check", slot, addr)   if pos == register[slot] jump to addr
    ("match",)              accept

Registers live in one array: slots [0, 2*ngroups+1] hold capture spans
(slot 0/1 = group 0), the remaining slots are loop temporaries.

Bounded repeats {m,n} are expanded (the repeated body re-uses the same
capture slots, so "last iteration wins" semantics hold).  Expansion is
guarded by MAX_PROGRAM_SIZE so pathological nesting fails cleanly.
"""

from .errors import PatternError
from .nodes import (
    Alternate,
    Anchor,
    AnyChar,
    CharClass,
    Concat,
    Group,
    Literal,
    Repeat,
)
from .options import IGNORECASE

#: Safety bound on the compiled program size (instructions).
MAX_PROGRAM_SIZE = 1_000_000


def _case_variants(ch):
    out = {ch}
    for v in (ch.lower(), ch.upper(), ch.swapcase()):
        if len(v) == 1:
            out.add(v)
    return frozenset(out)


def _expand_class_case(items):
    out = list(items)
    for it in items:
        if it[0] != "range":
            continue
        lo, hi = it[1], it[2]
        if lo == hi:
            for v in _case_variants(lo):
                if v != lo:
                    out.append(("range", v, v))
        elif "a" <= lo <= hi <= "z":
            out.append(("range", lo.upper(), hi.upper()))
        elif "A" <= lo <= hi <= "Z":
            out.append(("range", lo.lower(), hi.lower()))
    return out


class Compiler:
    def __init__(self, flags=0, temp_base=0):
        self.flags = flags
        self.prog = []
        self.temp_base = temp_base
        self.ntemps = 0

    # ------------------------------------------------------------------
    def emit(self, ins):
        self.prog.append(list(ins))
        if len(self.prog) > MAX_PROGRAM_SIZE:
            raise PatternError(
                "pattern too large after expansion (>%d instructions)"
                % MAX_PROGRAM_SIZE
            )
        return len(self.prog) - 1

    def _alloc_temp(self):
        slot = self.temp_base + self.ntemps
        self.ntemps += 1
        return slot

    # ------------------------------------------------------------------
    def compile_node(self, node):
        if isinstance(node, Literal):
            ch = node.ch
            if self.flags & IGNORECASE and len(_case_variants(ch)) > 1:
                self.emit(("ichar", _case_variants(ch)))
            else:
                self.emit(("char", ch))
        elif isinstance(node, AnyChar):
            self.emit(("any",))
        elif isinstance(node, CharClass):
            items = node.items
            if self.flags & IGNORECASE:
                items = tuple(_expand_class_case(items))
            self.emit(("class", items, node.negated))
        elif isinstance(node, Anchor):
            self.emit(("bol",) if node.kind == "^" else ("eol",))
        elif isinstance(node, Concat):
            for item in node.items:
                self.compile_node(item)
        elif isinstance(node, Group):
            if node.index is None:
                self.compile_node(node.child)
            else:
                self.emit(("save", 2 * node.index))
                self.compile_node(node.child)
                self.emit(("save", 2 * node.index + 1))
        elif isinstance(node, Alternate):
            self._alternate(node.branches)
        elif isinstance(node, Repeat):
            self._repeat(node)
        else:  # pragma: no cover - defensive
            raise PatternError("internal: unknown AST node %r" % (node,))

    # ------------------------------------------------------------------
    def _alternate(self, branches):
        end_jumps = []
        last = len(branches) - 1
        for i, branch in enumerate(branches):
            if i < last:
                split_idx = self.emit(("split", 0, 0))
                body = len(self.prog)
                self.compile_node(branch)
                jmp_idx = self.emit(("jmp", 0))
                nxt = len(self.prog)
                self.prog[split_idx] = ["split", body, nxt]
                end_jumps.append(jmp_idx)
            else:
                self.compile_node(branch)
        end = len(self.prog)
        for j in end_jumps:
            self.prog[j] = ["jmp", end]

    def _repeat(self, node):
        if node.hi is None and node.lo == 1:
            # "x+" / "x{1,}" compile to a plus loop directly.
            self._plus(node.child, node.greedy)
            return
        for _ in range(node.lo):
            self.compile_node(node.child)
        if node.hi is None:
            # {m,} -> m required copies, then a star
            self._star(node.child, node.greedy)
        else:
            for _ in range(node.hi - node.lo):
                self._quest(node.child, node.greedy)

    def _star(self, child, greedy):
        temp = self._alloc_temp()
        loop = len(self.prog)
        split_idx = self.emit(("split", 0, 0))
        body = len(self.prog)
        self.emit(("mark", temp))
        self.compile_node(child)
        check_idx = self.emit(("check", temp, 0))
        self.emit(("jmp", loop))
        end = len(self.prog)
        if greedy:
            self.prog[split_idx] = ["split", body, end]
        else:
            self.prog[split_idx] = ["split", end, body]
        self.prog[check_idx] = ["check", temp, end]

    def _plus(self, child, greedy):
        temp = self._alloc_temp()
        loop = len(self.prog)
        self.emit(("mark", temp))
        self.compile_node(child)
        check_idx = self.emit(("check", temp, 0))
        split_idx = self.emit(("split", 0, 0))
        end = len(self.prog)
        if greedy:
            self.prog[split_idx] = ["split", loop, end]
        else:
            self.prog[split_idx] = ["split", end, loop]
        self.prog[check_idx] = ["check", temp, end]

    def _quest(self, child, greedy):
        split_idx = self.emit(("split", 0, 0))
        body = len(self.prog)
        self.compile_node(child)
        end = len(self.prog)
        if greedy:
            self.prog[split_idx] = ["split", body, end]
        else:
            self.prog[split_idx] = ["split", end, body]


def compile_ast(node, flags, ngroups):
    """Compile *node*; returns (program, nregisters)."""
    temp_base = 2 * (ngroups + 1)
    compiler = Compiler(flags, temp_base)
    compiler.compile_node(node)
    compiler.emit(("match",))
    prog = [tuple(ins) for ins in compiler.prog]
    return prog, temp_base + compiler.ntemps
