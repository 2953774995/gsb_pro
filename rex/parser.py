"""Recursive-descent parser: pattern text -> explicit AST.

Grammar (EBNF-ish)::

    regex       := alternation
    alternation := concat ("|" concat)*
    concat      := repeat*
    repeat      := atom quantifier? "?"?        (suffix "?" = non-greedy)
    quantifier  := "*" | "+" | "?" | "{" m "}" | "{" m ",}" | "{" m "," n "}"
    atom        := "(" group-body | "[" class-body | "." | "^" | "$"
                 | escape | literal
    group-body  := ")"-terminated alternation, optionally prefixed by
                   "?:" (non-capturing) or "?P<name>" (named capture)
"""
from . import ast_nodes as ast
from .errors import RegexError
from .scanner import read_escape

MAX_REPEAT = 65535


class Parser:
    def __init__(self, src):
        if not isinstance(src, str):
            raise TypeError("pattern must be a string, not {}".format(
                type(src).__name__))
        self.src = src
        self.i = 0
        self.group_count = 0   # number of (unnamed) capturing groups
        self.slots = 0         # total capture slots (numbered + named)
        self.names = {}        # group name -> slot
        self.num2slot = {}     # group number -> slot

    # -- cursor helpers ----------------------------------------------------
    def peek(self):
        return self.src[self.i] if self.i < len(self.src) else ""

    def error(self, message, pos=None):
        raise RegexError(message, self.i if pos is None else pos)

    # -- entry point -------------------------------------------------------
    def parse(self):
        node = self.parse_alternation()
        if self.i < len(self.src):
            # parse_concat only stops at ")" or "|"; "|" is consumed by
            # parse_alternation, so anything left must be a stray ")".
            self.error("unmatched ')'")
        return node

    # -- grammar rules -----------------------------------------------------
    def parse_alternation(self):
        branches = [self.parse_concat()]
        while self.peek() == "|":
            self.i += 1
            branches.append(self.parse_concat())
        if len(branches) == 1:
            return branches[0]
        return ast.Alt(branches)

    def parse_concat(self):
        children = []
        while self.i < len(self.src) and self.peek() not in ")|":
            children.append(self.parse_repeat())
        if len(children) == 1:
            return children[0]
        return ast.Concat(children)

    def parse_repeat(self):
        atom = self.parse_atom()
        c = self.peek()
        if c in ("*", "+", "?"):
            qpos = self.i
            self.i += 1
            lo, hi = {"*": (0, None), "+": (1, None), "?": (0, 1)}[c]
        elif c == "{":
            qpos = self.i
            parsed = self._try_brace()
            if parsed is None:
                return atom  # "{" did not form a quantifier: literal char
            lo, hi, end = parsed
            self.i = end
        else:
            return atom
        if isinstance(atom, ast.Anchor):
            raise RegexError("cannot quantify an anchor", qpos)
        greedy = True
        if self.peek() == "?":
            greedy = False
            self.i += 1
        return ast.Repeat(atom, lo, hi, greedy)

    def parse_atom(self):
        c = self.peek()
        if c == "":
            self.error("unexpected end of pattern")
        if c in ("*", "+", "?"):
            self.error("nothing to repeat")
        if c == "(":
            return self.parse_group()
        if c == "[":
            return self.parse_class()
        if c == ".":
            self.i += 1
            return ast.Dot()
        if c == "^":
            self.i += 1
            return ast.Anchor("start")
        if c == "$":
            self.i += 1
            return ast.Anchor("end")
        if c == "\\":
            token, nxt = read_escape(self.src, self.i)
            self.i = nxt
            kind, value = token
            if kind == "class":
                return ast.CharClass(False, [("class", value)])
            return ast.Literal(value)
        if c == "{":
            if self._try_brace() is not None:
                self.error("nothing to repeat")
            self.i += 1
            return ast.Literal("{")
        self.i += 1
        return ast.Literal(c)

    def parse_group(self):
        start = self.i
        self.i += 1  # consume "("
        number = None
        name = None
        slot = None
        if self.peek() == "?":
            self.i += 1
            c = self.peek()
            if c == ":":
                self.i += 1  # non-capturing group
            elif c == "P":
                self.i += 1
                if self.peek() != "<":
                    self.error("expected '<' after '?P'")
                self.i += 1
                close = self.src.find(">", self.i)
                if close == -1:
                    self.error("unterminated group name", start)
                name = self.src[self.i:close]
                if not name or not (name[0].isalpha() or name[0] == "_") \
                        or not all(ch.isalnum() or ch == "_" for ch in name):
                    raise RegexError(
                        "bad group name {!r}".format(name), start)
                if name in self.names:
                    raise RegexError(
                        "redefinition of group name {!r}".format(name), start)
                self.i = close + 1
                self.slots += 1
                slot = self.slots
                self.names[name] = slot
            else:
                raise RegexError(
                    "unknown group extension '(?{}'".format(c), start)
        else:
            self.group_count += 1
            number = self.group_count
            self.slots += 1
            slot = self.slots
            self.num2slot[number] = slot
        child = self.parse_alternation()
        if self.peek() != ")":
            raise RegexError("unclosed group", start)
        self.i += 1  # consume ")"
        return ast.Group(child, number, name, slot)

    def parse_class(self):
        start = self.i
        self.i += 1  # consume "["
        negated = False
        if self.peek() == "^":
            negated = True
            self.i += 1
        items = []
        first = True
        while True:
            if self.i >= len(self.src):
                raise RegexError("unterminated character class", start)
            c = self.src[self.i]
            if c == "]" and not first:
                self.i += 1
                break
            first = False
            # Read one class item: an escape or a plain character.
            if c == "\\":
                token, nxt = read_escape(self.src, self.i)
                self.i = nxt
                if token[0] == "class":
                    if self.peek() == "-" and self.i + 1 < len(self.src) \
                            and self.src[self.i + 1] != "]":
                        raise RegexError(
                            "bad character range (class escape as range "
                            "bound)", self.i)
                    items.append(("class", token[1]))
                    continue
                lo = token[1]
            else:
                self.i += 1
                lo = c
            # A "-" followed by something other than "]" forms a range.
            if self.peek() == "-" and self.i + 1 < len(self.src) \
                    and self.src[self.i + 1] != "]":
                self.i += 1  # consume "-"
                if self.src[self.i] == "\\":
                    token, nxt = read_escape(self.src, self.i)
                    self.i = nxt
                    if token[0] == "class":
                        raise RegexError(
                            "bad character range (class escape as range "
                            "bound)", self.i - 1)
                    hi = token[1]
                else:
                    hi = self.src[self.i]
                    self.i += 1
                if ord(hi) < ord(lo):
                    raise RegexError(
                        "bad character range ({}-{})".format(lo, hi),
                        self.i - 1)
                items.append(("range", lo, hi))
            else:
                items.append(("char", lo))
        if not items:
            raise RegexError("empty character class", start)
        return ast.CharClass(negated, items)

    # -- {m} / {m,} / {m,n} quantifiers ------------------------------------
    def _try_brace(self):
        """If a valid brace quantifier starts at ``self.i``, return
        ``(lo, hi, end)`` (``hi`` is None for ``{m,}``; ``end`` is the index
        just past ``}``).  Return None if the text does not form a brace
        quantifier (the ``{`` is then a literal).  Raises RegexError for
        structurally valid but semantically bad quantifiers."""
        src = self.src
        i = self.i
        j = i + 1
        k = j
        while k < len(src) and src[k].isdigit():
            k += 1
        if k == j:
            return None  # no digits after "{"
        lo = int(src[j:k])
        if k < len(src) and src[k] == "}":
            hi = lo
            end = k + 1
        elif k < len(src) and src[k] == ",":
            k += 1
            j2 = k
            while k < len(src) and src[k].isdigit():
                k += 1
            if k >= len(src) or src[k] != "}":
                return None
            hi = int(src[j2:k]) if k > j2 else None
            end = k + 1
        else:
            return None
        if lo > MAX_REPEAT or (hi is not None and hi > MAX_REPEAT):
            raise RegexError(
                "repeat count too large (max {})".format(MAX_REPEAT), i)
        if hi is not None and lo > hi:
            raise RegexError("min repeat greater than max repeat", i)
        return lo, hi, end
