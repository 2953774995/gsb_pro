"""Tokenizer for the sqlq SQL dialect."""

from dataclasses import dataclass
from typing import List

from .errors import SqlqError


@dataclass
class Token:
    kind: str  # KEYWORD, IDENT, NUMBER, STRING, PUNCT, EOF
    value: object
    line: int
    column: int

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Token({!r}, {!r}, line={}, col={})".format(
            self.kind, self.value, self.line, self.column
        )


KEYWORDS = {
    "CREATE", "TABLE", "DROP", "INSERT", "INTO", "VALUES", "UPDATE", "SET",
    "DELETE", "FROM", "SELECT", "AS", "WHERE", "AND", "OR", "NOT", "NULL",
    "IS", "GROUP", "BY", "HAVING", "ORDER", "ASC", "DESC", "LIMIT",
    "OFFSET", "DISTINCT", "PRIMARY", "KEY", "INTEGER", "REAL", "TEXT",
    "INT",
}

# Punctuation / operators, longest first so two-character ones win.
PUNCTUATORS = ("<=", ">=", "!=", "<>", "==", "(", ")", ",", ";", "*", "/",
               "+", "-", "<", ">", "=", ".")


def tokenize(text):
    # type: (str) -> List[Token]
    """Split *text* into a list of tokens terminated by an EOF token."""
    tokens = []  # type: List[Token]
    length = len(text)
    pos = 0
    line = 1
    line_start = 0  # index at which the current line starts

    def column_at(index):
        return index - line_start + 1

    while pos < length:
        char = text[pos]

        # Whitespace (track newlines for position reporting).
        if char in " \t\r\n":
            if char == "\n":
                line += 1
                line_start = pos + 1
            pos += 1
            continue

        # Line comments: -- to end of line.
        if char == "-" and pos + 1 < length and text[pos + 1] == "-":
            pos += 2
            while pos < length and text[pos] != "\n":
                pos += 1
            continue

        # Block comments: /* ... */ and may nest.
        if char == "/" and pos + 1 < length and text[pos + 1] == "*":
            start_line, start_col = line, column_at(pos)
            depth = 1
            pos += 2
            while pos < length and depth > 0:
                if text[pos] == "\n":
                    line += 1
                    line_start = pos + 1
                if text[pos:pos + 2] == "/*":
                    depth += 1
                    pos += 2
                elif text[pos:pos + 2] == "*/":
                    depth -= 1
                    pos += 2
                else:
                    pos += 1
            if depth > 0:
                raise SqlqError("unterminated block comment", start_line,
                                start_col)
            continue

        # Identifiers and keywords.
        if char.isalpha() or char == "_":
            start = pos
            while pos < length and (text[pos].isalnum() or text[pos] == "_"):
                pos += 1
            word = text[start:pos]
            upper = word.upper()
            if upper in KEYWORDS:
                tokens.append(Token("KEYWORD", upper, line, column_at(start)))
            else:
                tokens.append(Token("IDENT", word, line, column_at(start)))
            continue

        # Numbers: digits[.digits][e...] style via float() fallback.
        if char.isdigit():
            start = pos
            while pos < length and text[pos].isdigit():
                pos += 1
            if pos < length and text[pos] == ".":
                pos += 1
                while pos < length and text[pos].isdigit():
                    pos += 1
            if pos < length and text[pos] in "eE":
                save = pos
                pos += 1
                if pos < length and text[pos] in "+-":
                    pos += 1
                if pos < length and text[pos].isdigit():
                    while pos < length and text[pos].isdigit():
                        pos += 1
                else:
                    pos = save
            raw = text[start:pos]
            try:
                number = float(raw) if ("." in raw or "e" in raw.lower()) \
                    else int(raw)
            except ValueError:
                raise SqlqError("invalid numeric literal '{}'".format(raw),
                                line, column_at(start))
            tokens.append(Token("NUMBER", number, line, column_at(start)))
            continue

        # String literals with '' used to escape a single quote.
        if char == "'":
            start = pos
            col = column_at(pos)
            pos += 1
            chars = []
            while True:
                if pos >= length:
                    raise SqlqError("unterminated string literal", line, col)
                if text[pos] == "'":
                    if pos + 1 < length and text[pos + 1] == "'":
                        chars.append("'")
                        pos += 2
                        continue
                    pos += 1
                    break
                if text[pos] == "\n":
                    line += 1
                    line_start = pos + 1
                chars.append(text[pos])
                pos += 1
            tokens.append(Token("STRING", "".join(chars), line, col))
            continue

        # Operators / punctuation.
        matched = None
        for punct in PUNCTUATORS:
            if text.startswith(punct, pos):
                matched = punct
                break
        if matched is None:
            raise SqlqError(
                "unexpected character {!r}".format(char), line, column_at(pos)
            )
        tokens.append(Token("PUNCT", matched, line, column_at(pos)))
        pos += len(matched)

    tokens.append(Token("EOF", None, line, column_at(pos)))
    return tokens
