"""Recursive-descent parser turning a pattern string into an explicit AST.

Grammar (roughly)::

    regex    := branch ( '|' branch )*
    branch   := quantified*
    quantified := atom quantifier? quantifier_modifier?
    atom     := '(' [ '?:' | '?P<' name '>' ] regex ')'
             |  '[' '^'? classitem+ ']'
             |  '.' | '^' | '$' | literal | escape

Named groups do not consume a numeric id; only unnamed capturing groups are
numbered 1..N in the order of their opening parentheses.
"""

from . import ast_nodes as ast
from .errors import RegexError
from .scanner import read_escape

MAX_REPEAT = 65535


class Parser(object):
    def __init__(self, pattern):
        self.pattern = pattern
        self.n = len(pattern)
        self.i = 0
        self.group_count = 0  # all groups (capturing slots), by open paren
        self.num_count = 0  # unnamed captures only, numbered 1..N
        self.names = {}

    def error(self, message, pos=None):
        if pos is None:
            pos = self.i
        raise RegexError(message, pos)

    def parse(self):
        node = self.parse_alt()
        if self.i != self.n:
            ch = self.pattern[self.i]
            if ch == ")":
                self.error("unbalanced parenthesis: unmatched ')'")
            self.error("unexpected character %r" % ch)
        return node

    # -- regex / branch -----------------------------------------------------

    def parse_alt(self):
        start = self.i
        branches = [self.parse_branch()]
        while self.i < self.n and self.pattern[self.i] == "|":
            self.i += 1
            branches.append(self.parse_branch())
        if len(branches) == 1:
            return branches[0]
        return ast.Alt(branches, start)

    def parse_branch(self):
        start = self.i
        nodes = []
        while self.i < self.n and self.pattern[self.i] not in "|)":
            ch = self.pattern[self.i]
            if ch in "*+?{":
                is_brace_quantifier = ch == "{" and self._peek_brace() is not None
                if ch == "{" and not is_brace_quantifier:
                    nodes.append(self.parse_atom())  # bare literal '{'
                    continue
                if not nodes:
                    self.error(
                        "nothing to repeat: quantifier '%s' not preceded by an atom" % ch
                    )
                if isinstance(nodes[-1], ast.Repeat):
                    self.error(
                        "multiple repeat: quantifier '%s' applied to another quantifier" % ch
                    )
                nodes[-1] = self.parse_quantifier(nodes[-1])
            else:
                atom = self.parse_atom()
                nodes.append(self.parse_quantifier(atom))
        if len(nodes) == 1:
            return nodes[0]
        return ast.Concat(nodes, start)

    # -- atoms --------------------------------------------------------------

    def parse_atom(self):
        pattern = self.pattern
        start = self.i
        ch = pattern[self.i]

        if ch == "(":
            return self.parse_group()
        if ch == "[":
            return self.parse_class()
        if ch == ".":
            self.i += 1
            return ast.Dot(start)
        if ch == "^":
            self.i += 1
            return ast.Anchor("start", start)
        if ch == "$":
            self.i += 1
            return ast.Anchor("end", start)
        if ch == "\\":
            item, next_i = read_escape(pattern, self.i, self.n)
            kind, value = item
            self.i = next_i
            if kind == "char":
                return ast.Literal(value, start)
            return ast.CharClass(False, [("set", value)], start)
        if ch in "{}":
            self.i += 1
            return ast.Literal(ch, start)
        if ch in "*+?":
            self.error("nothing to repeat: quantifier '%s' not preceded by an atom" % ch)
        self.i += 1
        return ast.Literal(ch, start)

    def parse_group(self):
        start = self.i
        pattern = self.pattern
        self.i += 1  # consume '('
        slot = self.group_count
        index = None
        name = None

        if self.i < self.n and pattern[self.i] == "?":
            if pattern.startswith("?:", self.i):
                self.i += 2
                slot = -1
            elif pattern.startswith("?P<", self.i):
                self.i += 3
                name_start = self.i
                while self.i < self.n and pattern[self.i] != ">":
                    self.i += 1
                if self.i >= self.n:
                    self.error("missing '>' after named group name", start)
                name = pattern[name_start : self.i]
                if not name or not (name[0].isalpha() or name[0] == "_") or not all(
                    c.isalnum() or c == "_" for c in name
                ):
                    self.error("bad character in group name %r" % name, name_start)
                if name in self.names:
                    self.error("redefinition of group name %r" % name, name_start)
                self.names[name] = slot
                self.i += 1  # consume '>'
            elif pattern.startswith("?#", self.i):
                self.error("unsupported feature: comment groups (?#...) are not implemented", start)
            elif pattern.startswith("?=", self.i) or pattern.startswith("?!", self.i):
                self.error("unsupported feature: lookahead assertions are not implemented", start)
            elif pattern.startswith("?<=", self.i) or pattern.startswith("?<!", self.i):
                self.error("unsupported feature: lookbehind assertions are not implemented", start)
            elif pattern.startswith("?P=", self.i):
                self.error("unsupported feature: backreferences are not implemented", start)
            else:
                self.error("unknown extension after '?' in group", self.i)

        if slot >= 0:
            self.group_count += 1
            if name is None:
                self.num_count += 1
                index = self.num_count

        body = self.parse_alt()
        if self.i >= self.n:
            self.error("missing ')' (unterminated group)", start)
        # current char must be ')'
        self.i += 1
        return ast.Group(body, slot, index, name, start)

    def parse_class(self):
        start = self.i
        pattern = self.pattern
        self.i += 1  # consume '['
        negated = False
        if self.i < self.n and pattern[self.i] == "^":
            negated = True
            self.i += 1

        items = []

        def read_class_item():
            if pattern[self.i] == "\\":
                item, next_i = read_escape(pattern, self.i, self.n)
                self.i = next_i
                return item
            ch = pattern[self.i]
            self.i += 1
            return ("char", ch)

        # A ']' immediately after '[' or '[^' is a literal member.
        if self.i < self.n and pattern[self.i] == "]":
            items.append(("char", "]"))
            self.i += 1

        while self.i < self.n and pattern[self.i] != "]":
            # A '-' in the first or last position is a literal.
            if pattern[self.i] == "-" and (not items or self._peek_class_end()):
                items.append(("char", "-"))
                self.i += 1
                continue
            kind, value = read_class_item()
            if self.i < self.n and pattern[self.i] == "-" and not self._peek_class_end():
                range_pos = self.i
                self.i += 1  # consume '-'
                end_kind, end_value = read_class_item()
                if kind != "char" or end_kind != "char":
                    self.error("bad character range: range endpoints must be literals", range_pos)
                if ord(value) > ord(end_value):
                    self.error(
                        "bad character range %r-%r (reversed endpoints)" % (value, end_value),
                        range_pos,
                    )
                items.append(("range", value, end_value))
            else:
                if kind == "char":
                    items.append(("char", value))
                else:
                    items.append(("set", value))
        if self.i >= self.n:
            self.error("unterminated character set: missing ']'", start)
        self.i += 1  # consume ']'
        return ast.CharClass(negated, items, start)

    def _peek_class_end(self):
        """True if the next character closes the current character class."""
        return self.i + 1 >= self.n or self.pattern[self.i + 1] == "]"

    # -- quantifiers --------------------------------------------------------

    def parse_quantifier(self, atom):
        pattern = self.pattern
        if self.i >= self.n:
            return atom
        ch = pattern[self.i]
        if ch not in "*+?{":
            return atom

        pos = self.i
        if ch in "*+?":
            if not self._repeatable(atom):
                self.error(
                    "multiple repeat: quantifier '%s' applied to another quantifier" % ch, pos
                )
            if ch == "*":
                lo, hi = 0, None
            elif ch == "+":
                lo, hi = 1, None
            else:
                lo, hi = 0, 1
            self.i += 1
        else:
            parsed = self._try_brace()
            if parsed is None:
                # Literal '{' that is not a valid quantifier.
                return atom
            lo, hi = parsed
            if not self._repeatable(atom):
                self.error("multiple repeat: quantifier applied to another quantifier", pos)

        greedy = True
        if self.i < self.n and pattern[self.i] == "?":
            greedy = False
            self.i += 1
        return ast.Repeat(atom, lo, hi, greedy, pos)

    @staticmethod
    def _repeatable(atom):
        return not isinstance(atom, ast.Repeat)

    def _peek_brace(self):
        """Return the (lo, hi) of a {m}/{m,}/{m,n} at self.i without moving."""
        saved = self.i
        result = self._try_brace()
        self.i = saved
        return result

    def _try_brace(self):
        """Parse {m}, {m,} or {m,n}; return None if it is not a quantifier.

        No whitespace is accepted, mirroring classic engine semantics, and a
        literal '{' is returned untouched otherwise.
        """
        pattern = self.pattern
        j = self.i + 1
        start_digits = j
        while j < self.n and pattern[j].isdigit():
            j += 1
        if j == start_digits:
            return None
        m = int(pattern[start_digits:j])
        if m > MAX_REPEAT:
            self.error("the repeat number %d is larger than %d" % (m, MAX_REPEAT), self.i)
        if j < self.n and pattern[j] == "}":
            self.i = j + 1
            return m, m
        if j < self.n and pattern[j] == ",":
            j += 1
            hi_digits = j
            while j < self.n and pattern[j].isdigit():
                j += 1
            if j < self.n and pattern[j] == "}":
                if j == hi_digits:
                    self.i = j + 1
                    return m, None
                n = int(pattern[hi_digits:j])
                if n > MAX_REPEAT:
                    self.error("the repeat number %d is larger than %d" % (n, MAX_REPEAT), self.i)
                if m > n:
                    self.error(
                        "bad repeat interval: min %d is greater than max %d" % (m, n), self.i
                    )
                self.i = j + 1
                return m, n
        return None


def parse(pattern):
    """Parse *pattern*; return ``(tree, meta)``.

    meta maps group name -> slot and also reports the total group / numbered
    group counts.
    """
    parser = Parser(pattern)
    tree = parser.parse()
    meta = {
        "names": parser.names,
        "group_count": parser.group_count,
        "num_count": parser.num_count,
    }
    return tree, meta
