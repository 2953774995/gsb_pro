"""Recursive-descent parser: pattern string -> explicit AST.

Grammar (EBNF-ish)::

    pattern      := alternation
    alternation  := concat ("|" concat)*
    concat       := repeat*
    repeat       := atom quantifier? "?"?        # trailing ? = lazy
    quantifier   := "*" | "+" | "?" | "{" m "}" | "{" m ",}" | "{" m "," n "}"
    atom         := "(" group-body | "[" class "]" | "." | "^" | "$"
                  | escape | literal
    group-body   := ")" ...                      # see _group()

All errors raise PatternError with a 1-based column.
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
from .options import MAX_REPEAT
from .scanner import CLASS_SHORTHANDS, HEX_DIGITS, SIMPLE_ESCAPES, Scanner


class Parser:
    def __init__(self, source):
        if not isinstance(source, str):
            raise TypeError("pattern must be a str, not %s" % type(source).__name__)
        self.sc = Scanner(source)
        self.ngroups = 0
        self.group_names = {}

    # ------------------------------------------------------------------
    def parse(self):
        """Parse the whole pattern; returns the root AST node."""
        node = self._alternation()
        if not self.sc.eof():
            ch = self.sc.peek()
            if ch == ")":
                raise PatternError("unmatched ')'", self.sc.pos)
            raise PatternError("unexpected character %r" % ch, self.sc.pos)
        return node

    # ------------------------------------------------------------------
    def _alternation(self):
        branches = [self._concat()]
        while self.sc.peek() == "|":
            self.sc.next()
            branches.append(self._concat())
        if len(branches) == 1:
            return branches[0]
        return Alternate(branches)

    def _concat(self):
        items = []
        while not self.sc.eof() and self.sc.peek() not in "|)":
            items.append(self._repeat())
        if not items:
            return Concat([])
        if len(items) == 1:
            return items[0]
        return Concat(items)

    # ------------------------------------------------------------------
    def _repeat(self):
        atom = self._atom()
        ch = self.sc.peek()
        if ch is None:
            return atom
        if ch in "*+?":
            col = self.sc.pos
            self.sc.next()
            self._check_repeatable(atom, col)
            lo, hi = {"*": (0, None), "+": (1, None), "?": (0, 1)}[ch]
            greedy = not self._lazy_suffix()
            return Repeat(atom, lo, hi, greedy)
        if ch == "{":
            col = self.sc.pos
            bounds = self._brace_quantifier()
            if bounds is None:
                return atom  # "{" was a literal; handled next round
            self._check_repeatable(atom, col)
            greedy = not self._lazy_suffix()
            return Repeat(atom, bounds[0], bounds[1], greedy)
        return atom

    @staticmethod
    def _check_repeatable(atom, col):
        if isinstance(atom, Anchor):
            raise PatternError("cannot apply a quantifier to an anchor", col)

    def _lazy_suffix(self):
        if self.sc.peek() == "?":
            self.sc.next()
            return True
        return False

    def _brace_quantifier(self):
        """Parse {m} / {m,} / {m,n}.  Returns (lo, hi) or None when the
        '{' does not start a valid quantifier (then it is a literal)."""
        sc = self.sc
        if sc.peek() != "{":
            return None
        col = sc.pos
        save = sc.i
        sc.next()  # {
        first = sc.peek()
        if first is None or not first.isdigit():
            sc.i = save
            return None
        lo = self._read_int()
        ch = sc.peek()
        if ch == "}":
            sc.next()
            hi = lo
        elif ch == ",":
            sc.next()
            ch = sc.peek()
            if ch == "}":
                sc.next()
                hi = None
            elif ch is not None and ch.isdigit():
                hi = self._read_int()
                if sc.peek() != "}":
                    sc.i = save
                    return None
                sc.next()
            else:
                sc.i = save
                return None
        else:
            sc.i = save
            return None
        if lo > MAX_REPEAT or (hi is not None and hi > MAX_REPEAT):
            raise PatternError(
                "repeat count too large (max %d)" % MAX_REPEAT, col
            )
        if hi is not None and lo > hi:
            raise PatternError(
                "min repeat %d greater than max repeat %d" % (lo, hi), col
            )
        return (lo, hi)

    def _read_int(self):
        sc = self.sc
        start = sc.i
        while not sc.eof() and sc.peek().isdigit():
            sc.next()
        return int(sc.source[start:sc.i])

    # ------------------------------------------------------------------
    def _atom(self):
        sc = self.sc
        ch = sc.peek()
        col = sc.pos
        if ch == "(":
            return self._group()
        if ch == "[":
            return self._class()
        if ch == ".":
            sc.next()
            return AnyChar()
        if ch == "^":
            sc.next()
            return Anchor("^")
        if ch == "$":
            sc.next()
            return Anchor("$")
        if ch == "\\":
            kind, value = self._escape()
            if kind == "lit":
                return Literal(value)
            pred, negated = CLASS_SHORTHANDS[value]
            item = ("npred", pred) if negated else ("pred", pred)
            return CharClass((item,), False)
        if ch in "*+?":
            raise PatternError("nothing to repeat", col)
        if ch == "{":
            if self._is_brace_quantifier():
                raise PatternError("nothing to repeat", col)
            sc.next()
            return Literal("{")
        sc.next()
        return Literal(ch)

    def _is_brace_quantifier(self):
        save = self.sc.i
        try:
            return self._brace_quantifier() is not None
        finally:
            self.sc.i = save

    # ------------------------------------------------------------------
    def _escape(self):
        r"""Parse one escape sequence (current char must be backslash).

        Returns ("lit", char) or ("class", letter) for \d \D \w \W \s \S.
        """
        sc = self.sc
        col = sc.pos
        sc.next()  # backslash
        if sc.eof():
            raise PatternError("trailing backslash", col)
        c = sc.next()
        if c in SIMPLE_ESCAPES:
            return ("lit", SIMPLE_ESCAPES[c])
        if c in CLASS_SHORTHANDS:
            return ("class", c)
        if c == "x":
            return ("lit", self._hex_escape(2, col, "\\x"))
        if c == "u":
            return ("lit", self._hex_escape(4, col, "\\u"))
        if c.isdigit():
            raise PatternError(
                "backreferences (\\%s) are not supported" % c, col
            )
        raise PatternError("unknown escape '\\%s'" % c, col)

    def _hex_escape(self, digits, col, kind):
        sc = self.sc
        start = sc.i
        for _ in range(digits):
            ch = sc.peek()
            if ch is None or ch not in HEX_DIGITS:
                raise PatternError(
                    "invalid %s escape: expected %d hex digits" % (kind, digits),
                    col,
                )
            sc.next()
        return chr(int(sc.source[start:sc.i], 16))

    # ------------------------------------------------------------------
    def _class(self):
        sc = self.sc
        col = sc.pos
        sc.next()  # [
        negated = False
        if sc.peek() == "^":
            sc.next()
            negated = True
        items = []
        first = True
        while True:
            if sc.eof():
                raise PatternError("unterminated character class", col)
            if sc.peek() == "]" and not first:
                sc.next()
                break
            first = False
            if sc.peek() == "\\":
                kind, value = self._escape()
                if kind == "class":
                    pred, neg = CLASS_SHORTHANDS[value]
                    items.append(("npred", pred) if neg else ("pred", pred))
                    continue
                ch1 = value
            else:
                ch1 = sc.next()
            items.append(self._maybe_range(ch1, col))
        if not items and not negated:
            raise PatternError("empty character class", col)
        return CharClass(tuple(items), negated)

    def _maybe_range(self, ch1, class_col):
        sc = self.sc
        if sc.peek() == "-" and sc.peek(1) not in ("]", None):
            sc.next()  # -
            if sc.peek() == "\\":
                kind, value = self._escape()
                if kind != "lit":
                    raise PatternError(
                        "bad character range: range end cannot be a class "
                        "shorthand", sc.pos
                    )
                hi = value
            else:
                hi = sc.next()
            if hi < ch1:
                raise PatternError(
                    "bad character range %r-%r: start > end" % (ch1, hi),
                    sc.pos,
                )
            return ("range", ch1, hi)
        return ("range", ch1, ch1)

    # ------------------------------------------------------------------
    def _group(self):
        sc = self.sc
        col = sc.pos
        sc.next()  # (
        capturing = True
        name = None
        if sc.peek() == "?":
            sc.next()
            if sc.eof():
                raise PatternError("unterminated group", col)
            c = sc.next()
            if c == ":":
                capturing = False
            elif c == "P":
                if sc.eof():
                    raise PatternError("unterminated group", col)
                c2 = sc.next()
                if c2 == "<":
                    name = self._read_group_name(col)
                elif c2 in ("=", "P"):
                    raise PatternError(
                        "backreferences (?P=%s) are not supported"
                        % ("name" if c2 == "=" else ""),
                        col,
                    )
                else:
                    raise PatternError(
                        "unsupported group extension '(?P%s'" % c2, col
                    )
            elif c in ("=", "!", "<"):
                raise PatternError(
                    "look-around assertions '(?%s' are not supported" % c, col
                )
            else:
                raise PatternError(
                    "unsupported group extension '(?%s'" % c, col
                )
        index = None
        if capturing:
            self.ngroups += 1
            index = self.ngroups
            if name is not None:
                if name in self.group_names:
                    raise PatternError(
                        "duplicate group name %r" % name, col
                    )
                self.group_names[name] = index
        child = self._alternation()
        if sc.eof():
            raise PatternError("unterminated group", col)
        sc.next()  # )
        return Group(index, name, child)

    def _read_group_name(self, col):
        sc = self.sc
        start = sc.i
        while not sc.eof() and sc.peek() != ">":
            sc.next()
        if sc.eof():
            raise PatternError("unterminated group name", col)
        name = sc.source[start:sc.i]
        sc.next()  # >
        ok = (
            len(name) > 0
            and (name[0].isalpha() or name[0] == "_")
            and all(c.isalnum() or c == "_" for c in name)
        )
        if not ok:
            raise PatternError("invalid group name %r" % name, col)
        return name


def parse(source):
    """Parse *source* and return (ast, ngroups, group_names)."""
    parser = Parser(source)
    ast = parser.parse()
    return ast, parser.ngroups, parser.group_names
