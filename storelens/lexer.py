"""Tokenizer for the storelens query language.

Produces a flat list of Token objects. Keywords are case-insensitive and
are normalized to uppercase. String literals use single quotes; a single
quote inside a string is escaped by doubling it ('').
"""

from .errors import StorelensError

KEYWORDS = {
    "CREATE", "TABLE", "DROP", "INSERT", "INTO", "VALUES", "UPDATE", "SET",
    "DELETE", "FROM", "SELECT", "WHERE", "GROUP", "BY", "HAVING", "ORDER",
    "ASC", "DESC", "LIMIT", "OFFSET", "DISTINCT", "AND", "OR", "NOT",
    "NULL", "IS", "AS", "PRIMARY", "KEY",
    "INTEGER", "REAL", "TEXT",
    "COUNT", "SUM", "AVG", "MIN", "MAX",
}

# Two-character operators must be tried before single-character ones.
_OPERATORS = ("!=", "<=", ">=", "=", "<", ">", "+", "-", "*", "/")
_PUNCT = ("(", ")", ",", ";")


class Token:
    __slots__ = ("type", "value", "line", "col")

    def __init__(self, type_, value, line, col):
        self.type = type_          # 'KEYWORD' | 'IDENT' | 'NUMBER' | 'STRING' | 'OP' | 'PUNCT' | 'EOF'
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self):
        return "Token(%r, %r, %d:%d)" % (self.type, self.value, self.line, self.col)


def tokenize(text):
    """Turn source text into a list of tokens ending with an EOF token."""
    tokens = []
    i = 0
    line = 1
    col = 1
    n = len(text)

    def advance(k=1):
        nonlocal i, line, col
        for _ in range(k):
            if i < n and text[i] == "\n":
                line += 1
                col = 1
            else:
                col += 1
            i += 1

    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            advance()
            continue
        if ch == "-" and i + 1 < n and text[i + 1] == "-":
            # line comment: -- ... to end of line
            while i < n and text[i] != "\n":
                advance()
            continue
        start_line, start_col = line, col

        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            word = text[i:j]
            advance(j - i)
            upper = word.upper()
            if upper in KEYWORDS:
                tokens.append(Token("KEYWORD", upper, start_line, start_col))
            else:
                tokens.append(Token("IDENT", word, start_line, start_col))
            continue

        if ch.isdigit() or (ch == "." and i + 1 < n and text[i + 1].isdigit()):
            j = i
            seen_dot = False
            while j < n and (text[j].isdigit() or (text[j] == "." and not seen_dot)):
                if text[j] == ".":
                    seen_dot = True
                j += 1
            num = text[i:j]
            advance(j - i)
            if seen_dot:
                tokens.append(Token("NUMBER", float(num), start_line, start_col))
            else:
                tokens.append(Token("NUMBER", int(num), start_line, start_col))
            continue

        if ch == "'":
            advance()
            buf = []
            while True:
                if i >= n:
                    raise StorelensError("unterminated string literal",
                                         start_line, start_col)
                if text[i] == "'":
                    if i + 1 < n and text[i + 1] == "'":
                        buf.append("'")
                        advance(2)
                        continue
                    advance()
                    break
                buf.append(text[i])
                advance()
            tokens.append(Token("STRING", "".join(buf), start_line, start_col))
            continue

        matched = False
        for op in _OPERATORS:
            if text.startswith(op, i):
                tokens.append(Token("OP", op, start_line, start_col))
                advance(len(op))
                matched = True
                break
        if matched:
            continue

        if ch in _PUNCT:
            tokens.append(Token("PUNCT", ch, start_line, start_col))
            advance()
            continue

        raise StorelensError("unexpected character %r" % ch, line, col)

    tokens.append(Token("EOF", None, line, col))
    return tokens
