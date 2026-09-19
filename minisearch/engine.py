"""The public search engine facade."""

from dataclasses import dataclass
from typing import Optional, Union

from .errors import SearchError
from .index import InvertedIndex
from .query import And, Not, Or, Phrase, Prefix, Term, parse
from .scorer import tf_idf
from .snippet import make_snippet
from .stopwords import DEFAULT_STOPWORDS
from .tokenizer import tokenize

DocId = Union[int, str]


@dataclass
class SearchResult:
    """One hit of :meth:`SearchEngine.search`."""

    doc_id: DocId
    score: float
    snippet: Optional[str] = None


def _intersect(left, right):
    """AND-combine two ``{doc_id: score}`` maps (scores are summed)."""
    if len(left) > len(right):
        left, right = right, left
    return {d: left[d] + right[d] for d in left if d in right}


def _union(left, right):
    """OR-combine two ``{doc_id: score}`` maps (scores are summed)."""
    merged = dict(left)
    for doc_id, score in right.items():
        merged[doc_id] = merged.get(doc_id, 0.0) + score
    return merged


class SearchEngine:
    """In-memory full-text search engine.

    Parameters
    ----------
    use_stopwords:
        When True (default) the built-in English stopword list is used.
    stopwords:
        An explicit iterable of stopwords replacing the built-in list
        (takes precedence over ``use_stopwords``).
    """

    def __init__(self, use_stopwords=True, stopwords=None):
        if stopwords is not None:
            self._stopwords = frozenset(w.lower() for w in stopwords)
        elif use_stopwords:
            self._stopwords = DEFAULT_STOPWORDS
        else:
            self._stopwords = None
        self._index = InvertedIndex()
        self._texts = {}

    # ------------------------------------------------------------------ #
    # document management
    # ------------------------------------------------------------------ #
    def add_document(self, doc_id, text):
        """Add or replace a document.  ``doc_id`` may be an int or a str."""
        if not isinstance(doc_id, (int, str)) or isinstance(doc_id, bool):
            raise TypeError("doc_id must be an int or a str")
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        tokens = tokenize(text, stopwords=self._stopwords)
        self._index.add_document(doc_id, tokens)
        self._texts[doc_id] = text

    def remove_document(self, doc_id):
        """Remove a document and all of its postings.

        Returns True when the document existed.
        """
        removed = self._index.remove_document(doc_id)
        self._texts.pop(doc_id, None)
        return removed

    def document_count(self):
        return self._index.document_count

    # ------------------------------------------------------------------ #
    # search
    # ------------------------------------------------------------------ #
    def search(self, query, top_k=10, with_snippet=False):
        """Run *query* and return an ordered list of :class:`SearchResult`.

        * ``top_k`` truncates the result list; ``0`` returns every hit.
        * ``with_snippet`` attaches an ~80-character hit summary.
        * Malformed queries raise :class:`SearchError`; no hits -> ``[]``.
        """
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 0:
            raise SearchError("top_k must be a non-negative integer")
        ast = parse(query)  # raises SearchError on invalid / empty queries
        if self._index.document_count == 0:
            return []
        scores = self._eval(ast)
        if not scores:
            return []
        ranked = sorted(scores.items(), key=lambda item: (-item[1], str(item[0])))
        if top_k > 0:
            ranked = ranked[:top_k]
        highlight = self._surface_terms(ast) if with_snippet else []
        results = []
        for doc_id, score in ranked:
            snippet = (
                make_snippet(self._texts.get(doc_id, ""), highlight)
                if with_snippet
                else None
            )
            results.append(SearchResult(doc_id=doc_id, score=score, snippet=snippet))
        return results

    # ------------------------------------------------------------------ #
    # query evaluation
    # ------------------------------------------------------------------ #
    def _eval(self, node):
        if isinstance(node, Term):
            return self._eval_term(node.text)
        if isinstance(node, Phrase):
            return self._eval_phrase(node.text)
        if isinstance(node, Prefix):
            return self._eval_prefix(node.prefix)
        if isinstance(node, And):
            return _intersect(self._eval(node.left), self._eval(node.right))
        if isinstance(node, Or):
            return _union(self._eval(node.left), self._eval(node.right))
        if isinstance(node, Not):
            excluded = self._eval(node.child)
            return {d: 0.0 for d in self._index.doc_ids() if d not in excluded}
        raise SearchError("unsupported query node: %r" % (node,))

    def _normalize(self, text):
        """Tokenize a query fragment exactly like document text."""
        return [t for t, _ in tokenize(text, stopwords=self._stopwords)]

    def _score_term(self, term):
        postings = self._index.postings(term)
        if not postings:
            return {}
        n_docs = self._index.document_count
        df = len(postings)
        return {
            doc_id: tf_idf(len(positions), df, n_docs)
            for doc_id, positions in postings.items()
        }

    def _eval_term(self, text):
        terms = self._normalize(text)
        if not terms:
            return {}  # e.g. a stopword-only term matches nothing
        scores = self._score_term(terms[0])
        for term in terms[1:]:
            # A multi-token term (e.g. a Chinese word) requires all tokens.
            scores = _intersect(scores, self._score_term(term))
        return scores

    def _eval_phrase(self, text):
        terms = self._normalize(text)
        if not terms:
            return {}
        postings_list = []
        for term in terms:
            postings = self._index.postings(term)
            if not postings:
                return {}
            postings_list.append(postings)
        candidates = set(postings_list[0])
        for postings in postings_list[1:]:
            candidates &= set(postings)
        n_docs = self._index.document_count
        width = len(terms)
        scores = {}
        for doc_id in candidates:
            position_sets = [set(p[doc_id]) for p in postings_list]
            for start in position_sets[0]:
                if all(
                    start + offset in position_sets[offset]
                    for offset in range(1, width)
                ):
                    scores[doc_id] = sum(
                        tf_idf(len(p[doc_id]), len(p), n_docs)
                        for p in postings_list
                    )
                    break
        return scores

    def _eval_prefix(self, prefix):
        normalized = prefix.lower()
        if not normalized:
            raise SearchError("wildcard query requires a non-empty prefix")
        scores = {}
        for term in self._index.terms_with_prefix(normalized):
            scores = _union(scores, self._score_term(term))
        return scores

    # ------------------------------------------------------------------ #
    # snippet support
    # ------------------------------------------------------------------ #
    @staticmethod
    def _surface_terms(node):
        """Collect the raw surface forms of the query for highlighting."""
        found = []

        def walk(n):
            if isinstance(n, Term):
                found.append(n.text)
            elif isinstance(n, Phrase):
                found.extend(n.text.split())
            elif isinstance(n, Prefix):
                found.append(n.prefix)
            elif isinstance(n, (And, Or)):
                walk(n.left)
                walk(n.right)
            elif isinstance(n, Not):
                walk(n.child)

        walk(node)
        return found
