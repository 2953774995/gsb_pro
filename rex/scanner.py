"""Character scanning helpers and the escape-sequence table.

The parser drives the scanner by index; ``read_escape`` decodes a single
escape sequence starting at a backslash and returns a token plus the index
just past the sequence.
"""
from .errors import RegexError

# Shorthand character classes: \d \D \w \W \s \S
CLASS_ESCAPES = frozenset("dDwWsS")

# Control-character escapes.
CONTROL_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "f": "\f",
    "v": "\v",
    "a": "\a",
}

# Punctuation that may be escaped to mean itself.
PUNCT_ESCAPES = frozenset("\\.^$*+?()[]{}|")

HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _read_hex(src, start, ndigits, col):
    digits = src[start:start + ndigits]
    if len(digits) < ndigits or any(c not in HEX_DIGITS for c in digits):
        raise RegexError("invalid hex escape", col)
    return chr(int(digits, 16))


def read_escape(src, i):
    """Decode the escape sequence whose backslash is at ``src[i]``.

    Returns ``(token, next_index)`` where ``token`` is either
    ``("char", c)`` for a single literal character or
    ``("class", code)`` for a shorthand class such as ``"d"`` or ``"W"``.

    Raises :class:`RegexError` for unknown escapes, trailing backslashes
    and (unsupported) backreferences.
    """
    col = i
    j = i + 1
    if j >= len(src):
        raise RegexError("trailing backslash", col)
    c = src[j]
    if c in CLASS_ESCAPES:
        return ("class", c), j + 1
    if c in CONTROL_ESCAPES:
        return ("char", CONTROL_ESCAPES[c]), j + 1
    if c.isdigit():
        raise RegexError(
            "backreferences (\\1..\\9) are not supported", col)
    if c == "x":
        return ("char", _read_hex(src, j + 1, 2, col)), j + 3
    if c == "u":
        return ("char", _read_hex(src, j + 1, 4, col)), j + 5
    if c in PUNCT_ESCAPES or not c.isalnum():
        # Any non-alphanumeric character may be escaped to mean itself
        # (covers \\ \. \* \+ \? \( \) \[ \] \| \{ \} \^ \$ \- \/ ...).
        return ("char", c), j + 1
    raise RegexError("unknown escape \\{}".format(c), col)
