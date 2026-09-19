"""Character scanning helpers and the escape table for rex.

The parser uses :func:`read_escape` both at the top level and inside
character classes, so escape semantics are identical in both contexts.
"""

from .errors import RegexError

# Single-character escapes mapping to a concrete character.
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
    "{": "{",
    "}": "}",
    "|": "|",
    "^": "^",
    "$": "$",
    "-": "-",
    "/": "/",
    '"': '"',
    "'": "'",
    "0": "\x00",
    "a": "\a",
    "f": "\f",
    "v": "\v",
}

# Shorthand character sets usable inside and outside character classes.
SET_ESCAPES = frozenset("dDwWsS")

HEX_ESCAPES = {"x": 2, "u": 4}

# Punctuation that may appear escaped even without a named meaning; it is
# treated as the literal character itself.
LITERAL_PUNCT = frozenset("!#%&,:;<=>@_`~")


def read_escape(pattern, i, end):
    """Read an escape sequence starting at the backslash ``pattern[i]``.

    Returns ``(node_tuple, next_index)`` where ``node_tuple`` is one of:
      ("char", ch)    a literal character
      ("set", code)   one of d/D/w/W/s/S
    """
    slash = i
    i += 1
    if i >= end:
        raise RegexError("bad escape (end of pattern): backslash at end of pattern", slash)
    marker = pattern[i]

    if marker in SIMPLE_ESCAPES:
        return ("char", SIMPLE_ESCAPES[marker]), i + 1

    if marker in SET_ESCAPES:
        return ("set", marker), i + 1

    if marker in HEX_ESCAPES:
        digits = HEX_ESCAPES[marker]
        hexpart = pattern[i + 1 : i + 1 + digits]
        if len(hexpart) < digits or any(c not in "0123456789abcdefABCDEF" for c in hexpart):
            raise RegexError(
                "bad escape: \\%s requires exactly %d hexadecimal digits" % (marker, digits),
                slash,
            )
        return ("char", chr(int(hexpart, 16))), i + 1 + digits

    if marker.isdigit():
        raise RegexError(
            "unsupported feature: backreferences (\\1 ...) are not implemented", slash
        )

    if marker in LITERAL_PUNCT:
        return ("char", marker), i + 1

    raise RegexError("bad escape: unknown escape sequence \\%s" % marker, slash)
