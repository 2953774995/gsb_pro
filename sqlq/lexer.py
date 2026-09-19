"""Hand-written tokenizer for the sqlq SQL dialect.

The lexer converts a SQL string into a list of :class:`Token` objects.  It
tracks 1-based line/column positions so the parser can report precise errors.
"""

from .errors import SqlqSyntaxError

# Token kinds ---------------------------------------------------------------

T_KEYWORD = "KEYWORD"
T_IDENT = "IDENT"
T_INTEGER = "INTEGER"
T_FLOAT = "FLOAT"
T_STRING = "STRING"
T_PUNCT = "PUNCT"
T_STAR = "STAR"  # * is tracked separately to make COUNT(*) / SELECT * easy
T_EOF = "EOF"

KEYWORDS = frozenset(
    """
    ALL AND ASC AS BETWEEN BY CREATE CROSS DEFAULT DELETE DESC DISTINCT DROP
    ELSE END EXISTS FALSE FROM FULL GROUP HAVING IF IN INNER INSERT INTEGER
    INTERSECT INTO IS JOIN KEY LEFT LIKE LIMIT MINUS NATURAL NOT NULL NULLS OFF
    OFFSET ON OR ORDER OUTER PRIMARY REAL REFERENCES RIGHT ROW ROWS SELECT
    SET TABLE TEXT THEN TRUE UNION UNIQUE UPDATE USING VALUES WHEN WHERE WITH
    """.split()
)
# BETWEEN/IN/LIKE/JOIN/UNION are reserved but not implemented; the parser
# rejects statements that try to use them.  Aggregate names COUNT/SUM/AVG/
# MIN/MAX stay plain identifiers so they parse as function calls.
# Multi-character punctuation, longest first.
_PUNCTUATORS = ("<=", ">=", "!=", "<>")
_SINGLE_PUNCT = set("(),;.*+-/=<>%")


class Token:
    __slots__ = ("kind", "value", "line", "column")

    def __init__(self, kind, value, line, column):
        self.kind = kind
        self.value = value
        self.line = line
        self.column = column

    def __repr__(self):
        return f"Token({self.kind}, {self.value!r}, {self.line}:{self.column})"

    def is_keyword(self, word):
        return self.kind == T_KEYWORD and self.value == word.upper()

    def is_punct(self, char):
        return self.kind in (T_PUNCT, T_STAR) and self.value == char


def tokenize(sql):
    """Return all tokens in ``sql`` including a trailing EOF token."""
    tokens = []
    i = 0
    line = 1
    col = 1
    length = len(sql)

    def advance(count=1):
        nonlocal i, line, col
        for _ in range(count):
            if i < length:
                if sql[i] == "\n":
                    line += 1
                    col = 1
                else:
                    col += 1
                i += 1

    while i < length:
        ch = sql[i]

        # Whitespace
        if ch in " \t\r\n":
            advance()
            continue

        start_line, start_col = line, col

        # SQL line comments: -- ...
        if ch == "-" and i + 1 < length and sql[i + 1] == "-":
            while i < length and sql[i] != "\n":
                advance()
            continue

        # C-style block comments: /* ... */ (comments do not nest)
        if ch == "/" and i + 1 < length and sql[i + 1] == "*":
            advance(2)
            closed = False
            while i < length:
                if sql[i] == "*" and i + 1 < length and sql[i + 1] == "/":
                    advance(2)
                    closed = True
                    break
                advance()
            if not closed:
                raise SqlqSyntaxError(
                    "unterminated block comment", start_line, start_col
                )
            continue

        # String literals with '' as an escaped single quote.
        if ch == "'":
            advance()  # opening quote
            buf = []
            while True:
                if i >= length:
                    raise SqlqSyntaxError(
                        "unterminated string literal", start_line, start_col
                    )
                if sql[i] == "'":
                    if i + 1 < length and sql[i + 1] == "'":
                        buf.append("'")
                        advance(2)
                        continue
                    advance()  # closing quote
                    break
                buf.append(sql[i])
                advance()
            tokens.append(Token(T_STRING, "".join(buf), start_line, start_col))
            continue

        # Identifiers / keywords.
        if ch.isalpha() or ch == "_":
            buf = []
            while i < length and (sql[i].isalnum() or sql[i] == "_"):
                buf.append(sql[i])
                advance()
            word = "".join(buf)
            upper = word.upper()
            if upper in KEYWORDS:
                tokens.append(Token(T_KEYWORD, upper, start_line, start_col))
            else:
                tokens.append(Token(T_IDENT, word, start_line, start_col))
            continue

        # Numeric literals.
        if ch.isdigit() or (ch == "." and i + 1 < length and sql[i + 1].isdigit()):
            is_float = False
            buf = []
            while i < length and sql[i].isdigit():
                buf.append(sql[i])
                advance()
            if i < length and sql[i] == ".":
                is_float = True
                buf.append(".")
                advance()
                while i < length and sql[i].isdigit():
                    buf.append(sql[i])
                    advance()
            # Optional exponent.
            if i < length and sql[i] in "eE":
                is_float = True
                buf.append(sql[i])
                advance()
                if i < length and sql[i] in "+-":
                    buf.append(sql[i])
                    advance()
                if i >= length or not sql[i].isdigit():
                    raise SqlqSyntaxError(
                        "malformed numeric literal: exponent missing digits",
                        start_line,
                        start_col,
                    )
                while i < length and sql[i].isdigit():
                    buf.append(sql[i])
                    advance()
            text = "".join(buf)
            try:
                if is_float:
                    value = float(text)
                    kind = T_FLOAT
                else:
                    value = int(text)
                    kind = T_INTEGER
            except ValueError:
                raise SqlqSyntaxError(
                    f"malformed numeric literal {text!r}", start_line, start_col
                )
            tokens.append(Token(kind, value, start_line, start_col))
            continue

        # Multi/single character punctuation.
        matched = None
        for cand in _PUNCTUATORS:
            if sql.startswith(cand, i):
                matched = cand
                break
        if matched is not None:
            advance(len(matched))
            tokens.append(Token(T_PUNCT, matched, start_line, start_col))
            continue
        if ch == "*":
            advance()
            tokens.append(Token(T_STAR, "*", start_line, start_col))
            continue
        if ch in _SINGLE_PUNCT:
            advance()
            tokens.append(Token(T_PUNCT, ch, start_line, start_col))
            continue

        raise SqlqSyntaxError(f"unexpected character {ch!r}", start_line, start_col)

    tokens.append(Token(T_EOF, None, line, col))
    return tokens
