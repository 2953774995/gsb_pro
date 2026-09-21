"""Query language: lexer, parser (to an AST) and index evaluation.

Syntax (see README.md):

* ``AND`` / ``OR`` / ``NOT`` (uppercase) boolean operators;
  precedence ``NOT`` > ``AND`` > ``OR``; parentheses for grouping.
* Juxtaposed atoms are an implicit ``AND`` (``a b`` == ``a AND b``).
* ``"exact phrase"`` positional phrase query.
* ``term*`` prefix query (matched against indexed, stemmed terms).
* A bare word is a term; words that tokenize to several tokens (e.g. any
  multi-character Chinese word) are matched as an exact token sequence.
* Bare terms are expanded through the synonym table (phrases/prefixes are
  not expanded).

Malformed queries (empty query, dangling operators, unbalanced parentheses,
unterminated quotes, empty prefix ``*`` ...) raise :class:`SearchError`.
"""

import math

from .errors import SearchError

# --------------------------------------------------------------------- #
# AST nodes
# --------------------------------------------------------------------- #


class Term:
    """A bare word; synonym-expanded and tokenized at evaluation time."""

    def __init__(self, raw):
        self.raw = raw


class Phrase:
    """An exact sequence of normalized tokens."""

    def __init__(self, tokens):
        self.tokens = tokens


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


# --------------------------------------------------------------------- #
# Lexer
# --------------------------------------------------------------------- #

_OPERATORS = ("AND", "OR", "NOT")


def _lex(query):
    tokens = []
    i, n = 0, len(query)
    while i < n:
        c = query[i]
        if c.isspace():
            i += 1
        elif c == '"':
            j = query.find('"', i + 1)
            if j == -1:
                raise SearchError("unterminated quote in phrase query")
            tokens.append(("PHRASE", query[i + 1 : j]))
            i = j + 1
        elif c == "(":
            tokens.append(("LP", c))
            i += 1
        elif c == ")":
            tokens.append(("RP", c))
            i += 1
        else:
            j = i
            while j < n and not query[j].isspace() and query[j] not in '()"':
                j += 1
            word = query[i:j]
            if word in _OPERATORS:
                tokens.append((word, word))
            elif word.endswith("*"):
                tokens.append(("PREFIX", word[:-1]))
            else:
                tokens.append(("TERM", word))
            i = j
    return tokens


# --------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------- #


class _Parser:
    def __init__(self, tokens, tokenizer):
        self.tokens = tokens
        self.pos = 0
        self.tokenizer = tokenizer

    def _peek(self):
        return self.tokens[self.pos][0] if self.pos < len(self.tokens) else None

    def _next(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def parse(self):
        if not self.tokens:
            raise SearchError("empty query")
        node = self._parse_or()
        if self.pos != len(self.tokens):
            raise SearchError("unexpected %r at end of query" % (self.tokens[self.pos][1],))
        return node

    def _parse_or(self):
        node = self._parse_and()
        while self._peek() == "OR":
            self._next()
            node = Or([node, self._parse_and()])
        return node

    def _parse_and(self):
        node = self._parse_unary()
        while True:
            kind = self._peek()
            if kind == "AND":
                self._next()
                rhs = self._parse_unary()
            elif kind in ("TERM", "PHRASE", "PREFIX", "LP", "NOT"):
                rhs = self._parse_unary()  # implicit AND
            else:
                break
            node = And([node, rhs])
        return node

    def _parse_unary(self):
        if self._peek() == "NOT":
            self._next()
            return Not(self._parse_unary())
        return self._parse_atom()

    def _parse_atom(self):
        if self.pos >= len(self.tokens):
            raise SearchError("unexpected end of query (missing operand)")
        kind, value = self._next()
        if kind == "TERM":
            toks = self.tokenizer.tokenize(value)
            if not toks:
                raise SearchError(
                    "term %r contains no searchable tokens (stop word?)" % (value,)
                )
            # A multi-token word (e.g. any Chinese word) is matched as an
            # exact token sequence inside Term evaluation, so synonym
            # expansion still applies to bare words.
            return Term(value)
        if kind == "PHRASE":
            toks = self.tokenizer.tokenize(value)
            if not toks:
                raise SearchError("phrase %r contains no searchable tokens" % (value,))
            return Phrase(toks)
        if kind == "PREFIX":
            prefix = value.strip().lower()
            if not prefix:
                raise SearchError("empty prefix query '*'")
            return Prefix(prefix)
        if kind == "LP":
            node = self._parse_or()
            if self._peek() != "RP":
                raise SearchError("missing closing parenthesis")
            self._next()
            return node
        if kind == "RP":
            raise SearchError("unbalanced closing parenthesis")
        raise SearchError("unexpected operator %r (missing operand)" % (value,))


def parse_query(query, tokenizer):
    """Parse *query* into an AST. Raises :class:`SearchError` when invalid."""
    if query is None or not str(query).strip():
        raise SearchError("empty query")
    return _Parser(_lex(str(query)), tokenizer).parse()


# --------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------- #


class Evaluator:
    """Evaluates an AST against an :class:`InvertedIndex`.

    Every node evaluates to ``{doc_id: score}``. Boolean nodes combine the
    children maps; scores are TF-IDF sums so boolean results stay ranked.
    """

    def __init__(self, index, tokenizer, synonyms=None):
        self.index = index
        self.tokenizer = tokenizer
        self.synonyms = synonyms
        self.n = index.doc_count
        self.all_docs = index.doc_ids

    # -- helpers ------------------------------------------------------- #
    def _idf(self, df):
        return math.log(1 + self.n / df)

    @staticmethod
    def _tf_weight(tf):
        return 1 + math.log(tf)

    def _phrase_occurrences(self, tokens):
        """Return ``{doc_id: occurrence_count}`` for an exact token sequence."""
        postings = self.index.postings
        first = postings.get(tokens[0])
        if not first:
            return {}
        docs = set(first)
        for tok in tokens[1:]:
            posting = postings.get(tok)
            if not posting:
                return {}
            docs &= posting.keys()
        if not docs:
            return {}
        result = {}
        for doc_id in docs:
            pos_sets = [set(postings[tok][doc_id][1]) for tok in tokens[1:]]
            count = 0
            for p0 in postings[tokens[0]][doc_id][1]:
                if all((p0 + i + 1) in pos_sets[i] for i in range(len(pos_sets))):
                    count += 1
            if count:
                result[doc_id] = count
        return result

    def _score_group(self, variant_token_lists):
        """Score a group of equivalent variants (synonyms / prefix matches).

        Each variant is a token list (length 1 -> term, longer -> phrase).
        Term frequencies of all variants are summed per document and the
        group df is the union document count, so variants never
        double-count.
        """
        doc_tf = {}
        for toks in variant_token_lists:
            if not toks:
                continue
            if len(toks) == 1:
                posting = self.index.postings.get(toks[0], {})
                occurrences = {d: tf for d, (tf, _pos) in posting.items()}
            else:
                occurrences = self._phrase_occurrences(toks)
            for doc_id, tf in occurrences.items():
                doc_tf[doc_id] = doc_tf.get(doc_id, 0) + tf
        df = len(doc_tf)
        if df == 0:
            return {}
        idf = self._idf(df)
        return {d: self._tf_weight(tf) * idf for d, tf in doc_tf.items()}

    # -- evaluation ----------------------------------------------------- #
    def evaluate(self, node):
        if isinstance(node, Term):
            raws = (
                self.synonyms.expand(node.raw) if self.synonyms else [node.raw]
            )
            variants = [self.tokenizer.tokenize(r) for r in raws]
            return self._score_group([v for v in variants if v])
        if isinstance(node, Phrase):
            return self._score_group([node.tokens])
        if isinstance(node, Prefix):
            matched = [
                t for t in self.index.postings if t.startswith(node.prefix)
            ]
            return self._score_group([[t] for t in matched])
        if isinstance(node, And):
            maps = [self.evaluate(c) for c in node.children]
            common = set(maps[0])
            for m in maps[1:]:
                common &= m.keys()
            return {d: sum(m[d] for m in maps) for d in common}
        if isinstance(node, Or):
            combined = {}
            for c in node.children:
                for d, s in self.evaluate(c).items():
                    combined[d] = combined.get(d, 0.0) + s
            return combined
        if isinstance(node, Not):
            excluded = set(self.evaluate(node.child))
            return {d: 0.0 for d in self.all_docs - excluded}
        raise SearchError("unknown query node: %r" % (node,))

    # -- terms used for snippets ---------------------------------------- #
    def positive_terms(self, node):
        """Collect indexed terms that may highlight a hit (skips NOT parts)."""
        if isinstance(node, Term):
            raws = (
                self.synonyms.expand(node.raw) if self.synonyms else [node.raw]
            )
            terms = set()
            for r in raws:
                terms.update(self.tokenizer.tokenize(r))
            return terms
        if isinstance(node, Phrase):
            return set(node.tokens)
        if isinstance(node, Prefix):
            return {
                t for t in self.index.postings if t.startswith(node.prefix)
            }
        if isinstance(node, (And, Or)):
            terms = set()
            for c in node.children:
                terms |= self.positive_terms(c)
            return terms
        return set()  # Not
