"""Query language: lexer, recursive-descent parser and AST nodes.

Grammar (precedence: NOT > AND > OR)::

    query   := or_expr
    or_expr := and_expr (OR and_expr)*
    and_expr:= not_expr ((AND | implicit) not_expr)*
    not_expr:= NOT not_expr | primary
    primary := "(" or_expr ")" | phrase | prefix | term
    phrase  := '"' ... '"'
    prefix  := term "*"

``AND`` / ``OR`` / ``NOT`` are recognised case-insensitively.  Two adjacent
operands without an explicit operator are combined with an implicit AND
(``a b`` == ``a AND b``).  Anything else (including Chinese text) is a term;
multi-token terms are normalised by the engine's tokenizer and combined
with AND semantics.
"""

from dataclasses import dataclass

from .errors import SearchError

__all__ = [
    "Term", "Phrase", "Prefix", "And", "Or", "Not",
    "parse",
]


# --------------------------------------------------------------------- #
# AST nodes
# --------------------------------------------------------------------- #
@dataclass(frozen=True)
class Term:
    text: str


@dataclass(frozen=True)
class Phrase:
    text: str


@dataclass(frozen=True)
class Prefix:
    prefix: str


@dataclass(frozen=True)
class And:
    left: object
    right: object


@dataclass(frozen=True)
class Or:
    left: object
    right: object


@dataclass(frozen=True)
class Not:
    child: object


# --------------------------------------------------------------------- #
# lexer
# --------------------------------------------------------------------- #
_OPERATORS = ("AND", "OR", "NOT")
_SPECIAL_CHARS = '()"'


def _lex(query):
    tokens = []
    i, n = 0, len(query)
    while i < n:
        ch = query[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "(":
            tokens.append(("LPAREN", ch))
            i += 1
        elif ch == ")":
            tokens.append(("RPAREN", ch))
            i += 1
        elif ch == '"':
            end = query.find('"', i + 1)
            if end == -1:
                raise SearchError("unterminated phrase: missing closing '\"'")
            tokens.append(("PHRASE", query[i + 1:end]))
            i = end + 1
        else:
            j = i
            while j < n and not query[j].isspace() and query[j] not in _SPECIAL_CHARS:
                j += 1
            word = query[i:j]
            upper = word.upper()
            if upper in _OPERATORS:
                tokens.append((upper, word))
            elif word == "*":
                raise SearchError("wildcard '*' requires a non-empty prefix, e.g. 'hel*'")
            elif word.endswith("*"):
                tokens.append(("PREFIX", word[:-1]))
            else:
                tokens.append(("TERM", word))
            i = j
    return tokens


# --------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------- #
class _Parser:
    def __init__(self, tokens):
        self._tokens = tokens
        self._pos = 0

    def _peek(self, kind=None):
        if self._pos >= len(self._tokens):
            return None if kind is None else False
        token = self._tokens[self._pos]
        return token if kind is None else token[0] == kind

    def _advance(self):
        token = self._tokens[self._pos]
        self._pos += 1
        return token

    def parse(self):
        node = self._parse_or()
        if self._pos != len(self._tokens):
            kind, value = self._tokens[self._pos]
            raise SearchError("unexpected %r in query" % value)
        return node

    def _parse_or(self):
        node = self._parse_and()
        while self._peek("OR"):
            self._advance()
            node = Or(node, self._parse_and())
        return node

    _PRIMARY_STARTERS = ("TERM", "PHRASE", "PREFIX", "LPAREN", "NOT")

    def _parse_and(self):
        node = self._parse_not()
        while True:
            if self._peek("AND"):
                self._advance()
                node = And(node, self._parse_not())
            elif self._peek() is not None and self._peek()[0] in self._PRIMARY_STARTERS:
                # Implicit AND between adjacent operands: "a b" == "a AND b".
                node = And(node, self._parse_not())
            else:
                return node

    def _parse_not(self):
        if self._peek("NOT"):
            self._advance()
            return Not(self._parse_not())
        return self._parse_primary()

    def _parse_primary(self):
        token = self._peek()
        if token is None:
            raise SearchError("unexpected end of query: an operand is missing")
        kind, value = token
        if kind == "LPAREN":
            self._advance()
            node = self._parse_or()
            if not self._peek("RPAREN"):
                raise SearchError("unbalanced parenthesis: missing ')'")
            self._advance()
            return node
        if kind == "RPAREN":
            raise SearchError("unexpected ')': unbalanced parenthesis")
        if kind in ("AND", "OR"):
            raise SearchError("dangling operator %r: missing operand" % value)
        self._advance()
        if kind == "TERM":
            return Term(value)
        if kind == "PREFIX":
            return Prefix(value)
        if kind == "PHRASE":
            return Phrase(value)
        raise SearchError("unexpected token %r" % value)  # pragma: no cover


def parse(query):
    """Parse *query* into an AST.  Raises :class:`SearchError` on any
    malformed input (empty query, dangling operators, unbalanced
    parentheses or quotes, ...)."""
    if not isinstance(query, str):
        raise SearchError("query must be a string, got %s" % type(query).__name__)
    tokens = _lex(query)
    if not tokens:
        raise SearchError("empty query: nothing to search for")
    return _Parser(tokens).parse()
