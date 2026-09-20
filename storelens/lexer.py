"""Tokenizer for the storelens query language.

Produces a list of Token objects from raw query text. Keywords are
case-insensitive; string literals use single quotes with '' as the
escape sequence for an embedded single quote.
"""

from .errors import StorelensError

KEYWORDS = {
    "CREATE", "TABLE", "DROP", "INSERT", "INTO", "VALUES",
    "UPDATE", "SET", "DELETE", "FROM", "SELECT", "WHERE",
    "AND", "OR", "NOT", "AS", "DISTINCT", "GROUP", "BY",
    "HAVING", "ORDER", "ASC", "DESC", "LIMIT", "OFFSET",
    "NULL", "IS", "PRIMARY", "KEY",
    "INTEGER", "REAL", "TEXT",
}

# Token types
KEYWORD = "KEYWORD"
IDENT = "IDENT"
STRING = "STRING"
NUMBER = "NUMBER"
OP = "OP"
PUNCT = "PUNCT"
EOF = "EOF"

_OPERATORS = ("!=", "<>", "<=", ">=", "=", "<", ">", "+", "-", "*", "/", "%")
_PUNCT = ("(", ")", ",", ";")


class Token:
    __slots__ = ("type", "value", "line", "col")

    def __init__(self, type_, value, line, col):
        self.type = type_
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self):
        return "Token(%s, %r, %d:%d)" % (self.type, self.value, self.line, self.col)


def _error(msg, line, col):
    return StorelensError("Syntax error at line %d, column %d: %s" % (line, col, msg))


def tokenize(text):
    """Convert query text into a list of tokens ending with an EOF token."""
    tokens = []
    i = 0
    line = 1
    col = 1
    n = len(text)

    def advance(count=1):
        nonlocal i, line, col
        for _ in range(count):
            if i < n and text[i] == "\n":
                line += 1
                col = 1
            else:
                col += 1
            i += 1

    while i < n:
        ch = text[i]
        # Whitespace
        if ch in " \t\r\n":
            advance()
            continue
        # Line comments: -- ...
        if ch == "-" and i + 1 < n and text[i + 1] == "-":
            while i < n and text[i] != "\n":
                advance()
            continue
        start_line, start_col = line, col
        # String literal
        if ch == "'":
            advance()
            chars = []
            while True:
                if i >= n:
                    raise _error("unterminated string literal", start_line, start_col)
                if text[i] == "'":
                    if i + 1 < n and text[i + 1] == "'":
                        chars.append("'")
                        advance(2)
                        continue
                    advance()
                    break
                chars.append(text[i])
                advance()
            tokens.append(Token(STRING, "".join(chars), start_line, start_col))
            continue
        # Number literal
        if ch.isdigit() or (ch == "." and i + 1 < n and text[i + 1].isdigit()):
            j = i
            seen_dot = False
            seen_exp = False
            while j < n:
                c = text[j]
                if c.isdigit():
                    j += 1
                elif c == "." and not seen_dot and not seen_exp:
                    seen_dot = True
                    j += 1
                elif c in "eE" and not seen_exp and j + 1 < n and (
                        text[j + 1].isdigit() or (
                            text[j + 1] in "+-" and j + 2 < n
                            and text[j + 2].isdigit())):
                    seen_exp = True
                    j += 1
                    if text[j] in "+-":
                        j += 1
                else:
                    break
            raw = text[i:j]
            try:
                value = float(raw) if (seen_dot or seen_exp) else int(raw)
            except ValueError:
                raise _error("invalid number literal %r" % raw, start_line, start_col)
            tokens.append(Token(NUMBER, value, start_line, start_col))
            advance(j - i)
            continue
        # Identifier or keyword
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            word = text[i:j]
            upper = word.upper()
            if upper in KEYWORDS:
                tokens.append(Token(KEYWORD, upper, start_line, start_col))
            else:
                tokens.append(Token(IDENT, word, start_line, start_col))
            advance(j - i)
            continue
        # Operators
        matched = None
        for op in _OPERATORS:
            if text.startswith(op, i):
                matched = op
                break
        if matched is not None:
            tokens.append(Token(OP, matched, start_line, start_col))
            advance(len(matched))
            continue
        # Punctuation
        if ch in _PUNCT:
            tokens.append(Token(PUNCT, ch, start_line, start_col))
            advance()
            continue
        raise _error("unexpected character %r" % ch, start_line, start_col)

    tokens.append(Token(EOF, None, line, col))
    return tokens
