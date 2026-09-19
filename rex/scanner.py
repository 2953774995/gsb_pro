"""Character scanner with escape-sequence handling.

The scanner walks the raw pattern string and produces a stream of
``Token`` objects.  Escape sequences are resolved here so the parser
only ever sees semantic tokens:

* ``Token("literal", ch, pos)`` -- a plain character (possibly the
  result of an escape such as ``\\n`` or ``\\x41``).
* ``Token("class_escape", name, pos)`` -- a character-class escape
  (``\\d \\D \\w \\W \\s \\S``) that may appear both inside and outside
  ``[...]``.
* ``Token("backref", digits, pos)`` -- a backreference such as ``\\1``.
  Backreferences are a known non-goal of this engine; the parser turns
  them into a clear "not supported" error.
* ``Token("meta", ch, pos)`` -- an unescaped metacharacter.
"""

from .errors import RegexError

# Single-character escapes that map to a control character.
CONTROL_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "f": "\f",
    "v": "\v",
    "a": "\a",
    "0": "\0",
}

# Escapes that simply yield the (otherwise special) character itself.
PUNCT_ESCAPES = set("\\.*+?()[]|{}^$-")

# Character-class escapes (value is the token payload name).
CLASS_ESCAPES = set("dDwWsS")

_HEX_DIGITS = set("0123456789abcdefABCDEF")


class Token:
    __slots__ = ("kind", "value", "pos")

    def __init__(self, kind, value, pos):
        self.kind = kind
        self.value = value
        self.pos = pos

    def __repr__(self):
        return "Token({!r}, {!r}, {!r})".format(self.kind, self.value, self.pos)


class Scanner:
    """Splits a pattern string into tokens, resolving escapes."""

    def __init__(self, pattern):
        if not isinstance(pattern, str):
            raise TypeError("pattern must be str, got %s" % type(pattern).__name__)
        self.pattern = pattern
        self.pos = 0
        self.length = len(pattern)

    def at_end(self):
        return self.pos >= self.length

    def peek(self):
        if self.at_end():
            return None
        return self.pattern[self.pos]

    def advance(self):
        ch = self.pattern[self.pos]
        self.pos += 1
        return ch

    def error(self, message, pos=None):
        raise RegexError(message, self.pos if pos is None else pos)

    def _read_hex(self, count, start):
        digits = self.pattern[self.pos:self.pos + count]
        if len(digits) < count or any(c not in _HEX_DIGITS for c in digits):
            self.error(
                "invalid hex escape: expected %d hex digits" % count, start
            )
        self.pos += count
        return chr(int(digits, 16))

    def read_escape(self):
        """Read one escape sequence; ``self.pos`` must be at the backslash.

        Returns a Token of kind ``literal``, ``class_escape`` or
        ``backref``.
        """
        start = self.pos
        self.pos += 1  # consume the backslash
        if self.at_end():
            self.error("trailing backslash at end of pattern", start)
        ch = self.advance()
        if ch in CONTROL_ESCAPES:
            return Token("literal", CONTROL_ESCAPES[ch], start)
        if ch in CLASS_ESCAPES:
            return Token("class_escape", ch, start)
        if ch in PUNCT_ESCAPES:
            return Token("literal", ch, start)
        if ch == "x":
            return Token("literal", self._read_hex(2, start), start)
        if ch == "u":
            return Token("literal", self._read_hex(4, start), start)
        if ch.isdigit():
            return Token("backref", ch, start)
        if ch.isalpha():
            self.error("unknown escape sequence \\%s" % ch, start)
        # Non-alphanumeric characters (e.g. \  \_ \/) escape to themselves.
        return Token("literal", ch, start)

    def read_token(self):
        """Read the next token outside of a character class."""
        start = self.pos
        ch = self.advance()
        if ch == "\\":
            self.pos = start
            return self.read_escape()
        if ch in "^$.|?*+()[]":
            return Token("meta", ch, start)
        if ch in "{}":
            return Token("meta", ch, start)
        return Token("literal", ch, start)

    def read_class_token(self):
        """Read the next token inside a character class.

        Inside ``[...]`` only ``]``, ``-`` and ``^`` keep a special
        meaning; every other metacharacter is a plain literal.
        """
        start = self.pos
        ch = self.advance()
        if ch == "\\":
            self.pos = start
            return self.read_escape()
        if ch in "]-^":
            return Token("meta", ch, start)
        return Token("literal", ch, start)
