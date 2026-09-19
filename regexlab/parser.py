"""Recursive-descent parser: pattern string -> AST.

Grammar (loosely)::

    regex        := alternation
    alternation  := concat ("|" concat)*
    concat       := repeat*
    repeat       := atom quantifier?
    quantifier   := ("*" | "+" | "?" | "{m}" | "{m,}" | "{m,n}" | "{,n}") "?"?
    atom         := "(" group-body ")" | "[" class "]" | "." | "^" | "$"
                    | escape | literal
"""

from .ast_nodes import (Alternation, AnyChar, CharClass, End, Group, Literal,
                        Predefined, Repeat, Sequence, Start, WordBoundary)
from .errors import RegexError

_QUANTIFIER_CHARS = ("*", "+", "?")
_PREDEFINED_KINDS = ("d", "D", "w", "W", "s", "S")
_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "f": "\f", "v": "\v",
                   "a": "\a"}


class Parser:
    def __init__(self, pattern):
        if not isinstance(pattern, str):
            raise RegexError("pattern must be a string, got %s"
                             % type(pattern).__name__)
        self.pattern = pattern
        self.pos = 0
        self.group_count = 0

    # -- entry point ----------------------------------------------------

    def parse(self):
        """Parse the whole pattern. Returns (ast, group_count)."""
        node = self._parse_alternation()
        if self.pos < len(self.pattern):
            # The only token that can stop a concat without being consumed
            # by a group is a stray ")".
            raise RegexError("unbalanced parenthesis: unexpected ')'",
                             self.pos)
        return node, self.group_count

    # -- helpers ----------------------------------------------------------

    def _peek(self, offset=0):
        idx = self.pos + offset
        if idx < len(self.pattern):
            return self.pattern[idx]
        return None

    # -- grammar rules ----------------------------------------------------

    def _parse_alternation(self):
        branches = [self._parse_concat()]
        while self._peek() == "|":
            self.pos += 1
            branches.append(self._parse_concat())
        if len(branches) == 1:
            return branches[0]
        return Alternation(branches)

    def _parse_concat(self):
        items = []
        while self.pos < len(self.pattern) and self._peek() not in ")|":
            items.append(self._parse_repeat())
        if len(items) == 1:
            return items[0]
        return Sequence(items)

    def _parse_repeat(self):
        atom = self._parse_atom()
        return self._apply_quantifier(atom)

    def _parse_atom(self):
        c = self._peek()
        if c == "(":
            return self._parse_group()
        if c == "[":
            return self._parse_char_class()
        if c == ".":
            self.pos += 1
            return AnyChar()
        if c == "^":
            self.pos += 1
            return Start()
        if c == "$":
            self.pos += 1
            return End()
        if c == "\\":
            return self._parse_escape(in_class=False)
        if c in _QUANTIFIER_CHARS:
            raise RegexError("nothing to repeat (dangling quantifier %r)" % c,
                             self.pos)
        if c == "{":
            if self._try_parse_brace_quantifier(dry_run=True) is not None:
                raise RegexError("nothing to repeat (dangling quantifier)",
                                 self.pos)
            # Not quantifier syntax: a literal '{'.
            self.pos += 1
            return Literal("{")
        # Ordinary literal character.
        self.pos += 1
        return Literal(c)

    def _parse_group(self):
        start = self.pos
        self.pos += 1  # consume "("
        if self._peek() == "?":
            if self._peek(1) == ":":
                self.pos += 2
                index = None
            else:
                raise RegexError(
                    "unknown group extension '(?%s'" % (self._peek(1) or ""),
                    start)
        else:
            self.group_count += 1
            index = self.group_count
        child = self._parse_alternation()
        if self._peek() != ")":
            raise RegexError("unbalanced parenthesis: missing ')'", start)
        self.pos += 1  # consume ")"
        return Group(child, index)

    # -- quantifiers ------------------------------------------------------

    def _apply_quantifier(self, atom):
        c = self._peek()
        if c in _QUANTIFIER_CHARS:
            self.pos += 1
            if c == "*":
                min_rep, max_rep = 0, None
            elif c == "+":
                min_rep, max_rep = 1, None
            else:
                min_rep, max_rep = 0, 1
        elif c == "{":
            bounds = self._try_parse_brace_quantifier()
            if bounds is None:
                return atom  # literal '{', no quantifier
            min_rep, max_rep = bounds
        else:
            return atom

        if isinstance(atom, (Start, End, WordBoundary)):
            raise RegexError("nothing to repeat (cannot quantify an "
                             "anchor or boundary)", self.pos - 1)
        if isinstance(atom, Repeat):
            raise RegexError("multiple repeat", self.pos - 1)

        greedy = True
        if self._peek() == "?":
            greedy = False
            self.pos += 1
        node = Repeat(atom, min_rep, max_rep, greedy)

        # A second quantifier right after this one is an error.
        nxt = self._peek()
        if nxt in _QUANTIFIER_CHARS:
            raise RegexError("multiple repeat", self.pos)
        if nxt == "{" and self._try_parse_brace_quantifier(dry_run=True) \
                is not None:
            raise RegexError("multiple repeat", self.pos)
        return node

    def _try_parse_brace_quantifier(self, dry_run=False):
        """Parse ``{m}``, ``{m,}``, ``{m,n}`` or ``{,n}``.

        Returns (min, max) or None if the text after ``{`` is not valid
        quantifier syntax (in which case ``{`` is a literal). With
        ``dry_run=True`` the parser position is left untouched.
        """
        saved = self.pos
        i = self.pos + 1  # skip "{"
        n = len(self.pattern)

        def read_digits(pos):
            start = pos
            while pos < n and self.pattern[pos].isdigit():
                pos += 1
            return self.pattern[start:pos], pos

        lo_digits, i = read_digits(i)
        if self.pattern[i:i + 1] == "}":
            if not lo_digits:
                return None
            i += 1
            bounds = (int(lo_digits), int(lo_digits))
        elif self.pattern[i:i + 1] == ",":
            i += 1
            hi_digits, i = read_digits(i)
            if self.pattern[i:i + 1] != "}":
                return None
            i += 1
            if not lo_digits and not hi_digits:
                return None  # "{,}" is not a quantifier
            min_rep = int(lo_digits) if lo_digits else 0
            max_rep = int(hi_digits) if hi_digits else None
            if max_rep is not None and min_rep > max_rep:
                raise RegexError(
                    "min repeat greater than max repeat", saved)
            bounds = (min_rep, max_rep)
        else:
            return None
        if not dry_run:
            self.pos = i
        return bounds

    # -- character classes --------------------------------------------------

    def _parse_char_class(self):
        start = self.pos
        self.pos += 1  # consume "["
        negated = False
        if self._peek() == "^":
            negated = True
            self.pos += 1
        items = []
        first = True
        while True:
            if self.pos >= len(self.pattern):
                raise RegexError("unterminated character set", start)
            c = self.pattern[self.pos]
            if c == "]" and not first:
                self.pos += 1
                break
            first = False
            item = self._parse_class_atom(start)
            # A range like a-z: only between two plain characters, and
            # only when "-" is not the last character before "]".
            if (item[0] == "range" and item[1] == item[2]
                    and self._peek() == "-" and self._peek(1) not in (None, "]")):
                self.pos += 1  # consume "-"
                hi_item = self._parse_class_atom(start)
                if hi_item[0] != "range" or hi_item[1] != hi_item[2]:
                    raise RegexError(
                        "bad character range (predefined class as range "
                        "endpoint)", self.pos - 1)
                lo, hi = item[1], hi_item[2]
                if hi < lo:
                    raise RegexError(
                        "bad character range %s-%s (out of order)"
                        % (chr(lo), chr(hi)), self.pos - 1)
                item = ("range", lo, hi)
            items.append(item)
        return CharClass(items, negated)

    def _parse_class_atom(self, class_start):
        """Parse one character or escape inside a character class.

        Returns ("range", ord, ord) for a plain character or
        ("pre", kind) for a predefined class like \\d.
        """
        c = self.pattern[self.pos]
        if c == "\\":
            node = self._parse_escape(in_class=True)
            if isinstance(node, Predefined):
                return ("pre", node.kind)
            return ("range", ord(node.char), ord(node.char))
        self.pos += 1
        return ("range", ord(c), ord(c))

    # -- escapes ------------------------------------------------------------

    def _parse_escape(self, in_class):
        start = self.pos
        self.pos += 1  # consume "\"
        if self.pos >= len(self.pattern):
            raise RegexError("bad escape (end of pattern)", start)
        c = self.pattern[self.pos]
        self.pos += 1
        if c in _SIMPLE_ESCAPES:
            return Literal(_SIMPLE_ESCAPES[c])
        if c in _PREDEFINED_KINDS:
            return Predefined(c)
        if not in_class:
            if c == "b":
                return WordBoundary(negated=False)
            if c == "B":
                return WordBoundary(negated=True)
        elif c == "b":
            return Literal("\x08")  # backspace, like Python's re
        if c.isdigit():
            raise RegexError(
                "backreferences (\\%s) are not supported" % c, start)
        if c.isalpha():
            raise RegexError("bad escape \\%s" % c, start)
        # Escaped punctuation (\. \\ \* \[ etc.) is the literal character.
        return Literal(c)


def parse(pattern):
    """Parse *pattern* and return ``(ast, group_count)``."""
    return Parser(pattern).parse()
