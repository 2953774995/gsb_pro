"""Query language lexer and recursive-descent parser.

Grammar (operators are case-insensitive, AND binds tighter than OR,
NOT is a unary prefix operator applying to the following sub-expression):

    query    := or_expr
    or_expr  := and_expr (OR and_expr)*
    and_expr := not_expr ((AND)? not_expr)*      # juxtaposition = implicit AND
    not_expr := NOT not_expr | primary
    primary  := '(' or_expr ')' | PHRASE | PREFIX | TERM

Adjacent operands without an explicit operator are combined with an
implicit AND (e.g. "python web" == "python AND web").
"""

from .tokenizer import tokenize


class SearchError(Exception):
    """Raised for malformed queries or invalid search requests."""


# --- AST nodes -------------------------------------------------------------

class Term:
    def __init__(self, term, raw=None):
        self.term = term
        self.raw = raw if raw is not None else term


class Phrase:
    def __init__(self, terms, raw_terms):
        self.terms = terms
        self.raw_terms = raw_terms


class Prefix:
    def __init__(self, prefix):
        self.prefix = prefix


class And:
    def __init__(self, children):
        self.children = children


class Or:
    def __init__(self, children):
        self.children = children


class Not:
    def __init__(self, child):
        self.child = child


# --- Lexer -----------------------------------------------------------------

_LPAREN, _RPAREN, _AND, _OR, _NOT, _TERM, _PHRASE, _PREFIX = range(8)


def _is_word_char(char):
    return char.isalnum() or "一" <= char <= "鿿" or char == "_"


def _lex(query):
    tokens = []
    index = 0
    length = len(query)
    while index < length:
        char = query[index]
        if char.isspace():
            index += 1
            continue
        if char == "(":
            tokens.append((_LPAREN, "("))
            index += 1
            continue
        if char == ")":
            tokens.append((_RPAREN, ")"))
            index += 1
            continue
        if char == '"':
            end = query.find('"', index + 1)
            if end == -1:
                raise SearchError('unterminated phrase: missing closing "')
            tokens.append((_PHRASE, query[index + 1:end]))
            index = end + 1
            continue
        if char == "*":
            raise SearchError("wildcard '*' must follow a term (prefix query)")
        if _is_word_char(char):
            start = index
            while index < length and _is_word_char(query[index]):
                index += 1
            word = query[start:index]
            if index < length and query[index] == "*":
                tokens.append((_PREFIX, word))
                index += 1
                continue
            lowered = word.lower()
            if lowered == "and":
                tokens.append((_AND, word))
            elif lowered == "or":
                tokens.append((_OR, word))
            elif lowered == "not":
                tokens.append((_NOT, word))
            else:
                tokens.append((_TERM, word))
            continue
        raise SearchError("unexpected character %r in query" % char)
    return tokens


# --- Parser ----------------------------------------------------------------

class _Parser:
    def __init__(self, tokens, use_stop_words, stop_words, stem):
        self.tokens = tokens
        self.pos = 0
        self.use_stop_words = use_stop_words
        self.stop_words = stop_words
        self.stem = stem

    def _peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return (None, None)

    def _next(self):
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def parse(self):
        node = self._parse_or()
        if self.pos != len(self.tokens):
            kind, value = self.tokens[self.pos]
            if kind == _RPAREN:
                raise SearchError("unbalanced parenthesis: unexpected ')'")
            raise SearchError("unexpected token %r" % value)
        return node

    def _parse_or(self):
        children = [self._parse_and()]
        while self._peek()[0] == _OR:
            self._next()
            children.append(self._parse_and())
        return children[0] if len(children) == 1 else Or(children)

    def _parse_and(self):
        children = [self._parse_not()]
        while True:
            kind, _ = self._peek()
            if kind == _AND:
                self._next()
                children.append(self._parse_not())
            elif kind in (_TERM, _PHRASE, _PREFIX, _NOT, _LPAREN):
                children.append(self._parse_not())  # implicit AND
            else:
                break
        return children[0] if len(children) == 1 else And(children)

    def _parse_not(self):
        if self._peek()[0] == _NOT:
            self._next()
            return Not(self._parse_not())
        return self._parse_primary()

    def _parse_primary(self):
        kind, value = self._peek()
        if kind == _LPAREN:
            self._next()
            node = self._parse_or()
            if self._peek()[0] != _RPAREN:
                raise SearchError("unbalanced parenthesis: missing ')'")
            self._next()
            return node
        if kind == _TERM:
            self._next()
            terms = self._normalize(value)
            if not terms:
                raise SearchError(
                    "term %r was removed entirely by stop-word filtering" % value)
            return Term(terms[0], raw=value.lower())
        if kind == _PREFIX:
            self._next()
            prefix = value.lower()
            if not prefix:
                raise SearchError("invalid prefix %r" % value)
            return Prefix(prefix)
        if kind == _PHRASE:
            self._next()
            pairs = tokenize(value, use_stop_words=self.use_stop_words,
                             stop_words=self.stop_words, stem=self.stem)
            if not pairs:
                raise SearchError("phrase %r contains no searchable terms" % value)
            terms = [term for term, _ in pairs]
            raw_terms = [word.lower() for word in value.split()]
            if len(terms) == 1:
                return Term(terms[0], raw=raw_terms[0] if raw_terms else terms[0])
            return Phrase(terms, raw_terms)
        if kind is None:
            raise SearchError("unexpected end of query: missing operand")
        raise SearchError("operator %r is missing an operand" % value)

    def _normalize(self, word):
        pairs = tokenize(word, use_stop_words=self.use_stop_words,
                         stop_words=self.stop_words, stem=self.stem)
        return [term for term, _ in pairs]


def parse_query(query, use_stop_words=True, stop_words=None, stem=True):
    """Parse a query string into an AST. Raises SearchError on bad input."""
    if not isinstance(query, str):
        raise SearchError("query must be a string")
    if not query.strip():
        raise SearchError("empty query")
    tokens = _lex(query)
    if not tokens:
        raise SearchError("empty query")
    parser = _Parser(tokens, use_stop_words, stop_words, stem)
    return parser.parse()
