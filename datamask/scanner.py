"""Character scanner and escape tables for the pattern language.

This module is the lowest layer of the front-end: it knows nothing
about grammar, only how to walk the source string column by column and
what each escape sequence means.  Keeping the tables here makes the
supported escape set explicit and auditable.
"""


class Scanner:
    """A cursor over the pattern source with 1-based column tracking."""

    __slots__ = ("source", "i")

    def __init__(self, source):
        self.source = source
        self.i = 0

    def eof(self):
        return self.i >= len(self.source)

    def peek(self, offset=0):
        """Return the char at i+offset without consuming it (None at EOF)."""
        j = self.i + offset
        if 0 <= j < len(self.source):
            return self.source[j]
        return None

    def next(self):
        """Consume and return the current char."""
        ch = self.source[self.i]
        self.i += 1
        return ch

    @property
    def pos(self):
        """1-based column of the current (not yet consumed) character."""
        return self.i + 1


#: Simple single-character escapes: escape letter -> literal character.
SIMPLE_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "\\": "\\",
    ".": ".",
    "*": "*",
    "+": "+",
    "?": "?",
    "(": "(",
    ")": ")",
    "[": "[",
    "]": "]",
    "|": "|",
    "{": "{",
    "}": "}",
    "^": "^",
    "$": "$",
    "-": "-",
    "/": "/",
}

#: Shorthand character classes: escape letter -> (predicate name, negated).
#: \d digit, \w word char, \s whitespace; upper-case variants negate.
CLASS_SHORTHANDS = {
    "d": ("digit", False),
    "D": ("digit", True),
    "w": ("word", False),
    "W": ("word", True),
    "s": ("space", False),
    "S": ("space", True),
}

HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
