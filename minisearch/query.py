"""Query language: lexer, recursive-descent parser and AST utilities.

Grammar (precedence: NOT > AND > OR)::

    expr    := or_expr
    or_expr := and_expr (OR and_expr)*
    and_expr:= not_expr (AND not_expr)*
    not_expr:= NOT not_expr | primary
    primary := '(' expr ')' | '"' phrase '"' | prefix | term
    prefix  := word '*'

AST nodes are tuples: ('term', w) ('prefix', p) ('phrase', text)
('and', a, b) ('or', a, b) ('not', a).
"""

from .errors import SearchError

OPERATORS = {"AND", "OR", "NOT"}


def lex(query):
    """Split a raw query string into tokens.

    Token kinds: LP, RP, PHRASE (quoted text), TERM.
    """
    tokens = []
    i = 0
    n = len(query)
    while i < n:
        ch = query[i]
        if ch.isspace():
            i += 1
        elif ch == "(":
            tokens.append(("LP", ch))
            i += 1
        elif ch == ")":
            tokens.append(("RP", ch))
            i += 1
        elif ch == '"':
            j = query.find('"', i + 1)
            if j == -1:
                raise SearchError("unterminated phrase: missing closing quote")
            tokens.append(("PHRASE", query[i + 1 : j]))
            i = j + 1
        else:
            j = i
            while j < n and not query[j].isspace() and query[j] not in '()"':
                j += 1
            tokens.append(("TERM", query[i:j]))
            i = j
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def advance(self):
        token = self.peek()
        self.pos += 1
        return token

    def accept_keyword(self, keyword):
        token = self.peek()
        if token and token[0] == "TERM" and token[1].upper() == keyword:
            self.pos += 1
            return True
        return False

    def parse_or(self):
        left = self.parse_and()
        while self.accept_keyword("OR"):
            left = ("or", left, self.parse_and())
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.accept_keyword("AND"):
            left = ("and", left, self.parse_not())
        return left

    def parse_not(self):
        if self.accept_keyword("NOT"):
            return ("not", self.parse_not())
        return self.parse_primary()

    def parse_primary(self):
        token = self.advance()
        if token is None:
            raise SearchError("unexpected end of query: expected a term, phrase or '('")
        kind, value = token
        if kind == "LP":
            node = self.parse_or()
            closing = self.advance()
            if closing is None or closing[0] != "RP":
                raise SearchError("missing closing parenthesis")
            return node
        if kind == "RP":
            raise SearchError("unexpected ')': no matching opening parenthesis")
        if kind == "PHRASE":
            if not value.strip():
                raise SearchError("empty phrase")
            return ("phrase", value)
        # TERM
        if value.upper() in OPERATORS:
            raise SearchError("operator %r is missing an operand" % value)
        if "*" in value:
            if not value.endswith("*") or value.count("*") > 1:
                raise SearchError("'*' is only allowed once, at the end of a term")
            prefix = value[:-1]
            if not prefix:
                raise SearchError("empty prefix before '*'")
            return ("prefix", prefix)
        return ("term", value)


def parse(query):
    """Parse a query string into an AST; raise SearchError on bad input."""
    if query is None or not query.strip():
        raise SearchError("empty query")
    tokens = lex(query)
    if not tokens:
        raise SearchError("empty query")
    parser = _Parser(tokens)
    node = parser.parse_or()
    leftover = parser.peek()
    if leftover is not None:
        raise SearchError("unexpected token %r: missing operator?" % leftover[1])
    return node


def collect_terms(node):
    """Collect raw (lowercased, unstemmed) query words for snippet lookup."""
    kind = node[0]
    if kind == "term":
        return [node[1].lower()]
    if kind == "prefix":
        return [node[1].lower()]
    if kind == "phrase":
        return [w.lower() for w in node[1].split()]
    if kind in ("and", "or"):
        return collect_terms(node[1]) + collect_terms(node[2])
    return collect_terms(node[1])
