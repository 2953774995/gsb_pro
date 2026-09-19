"""SearchEngine: the public facade tying tokenizer, index, parser, scorer."""

import math

from .errors import SearchError
from .index import InvertedIndex
from .query import collect_terms, parse
from .scorer import Scorer
from .snippet import make_snippet
from .tokenizer import Tokenizer


class SearchEngine:
    def __init__(self, use_stopwords=True, stopwords=None):
        self.tokenizer = Tokenizer(use_stopwords=use_stopwords, stopwords=stopwords)
        self.index = InvertedIndex()
        self.scorer = Scorer(self.index)

    # ------------------------------------------------------------------ #
    # document management
    # ------------------------------------------------------------------ #
    def add_document(self, doc_id, text):
        if not isinstance(doc_id, (int, str)) or isinstance(doc_id, bool):
            raise TypeError("doc_id must be an int or a str")
        if not isinstance(text, str):
            raise TypeError("text must be a str")
        tokens = self.tokenizer.tokenize(text)
        self.index.add_document(doc_id, tokens, text)

    def remove_document(self, doc_id):
        return self.index.remove_document(doc_id)

    def document_count(self):
        return self.index.document_count()

    # ------------------------------------------------------------------ #
    # search
    # ------------------------------------------------------------------ #
    def search(self, query, top_k=10, with_snippet=False):
        """Run a query and return [{'doc_id', 'score', ['snippet']}, ...]
        sorted by descending score.  top_k=0 returns every hit."""
        if top_k is None or top_k < 0:
            raise SearchError("top_k must be >= 0")
        ast = parse(query)  # raises SearchError for empty/invalid queries
        if self.index.document_count() == 0:
            return []
        scores = self._eval(ast)
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], str(kv[0])))
        if top_k > 0:
            ranked = ranked[:top_k]
        terms = collect_terms(ast)
        results = []
        for doc_id, score in ranked:
            hit = {"doc_id": doc_id, "score": score}
            if with_snippet:
                hit["snippet"] = make_snippet(self.index.documents[doc_id], terms)
            results.append(hit)
        return results

    # ------------------------------------------------------------------ #
    # AST evaluation -> {doc_id: score}
    # ------------------------------------------------------------------ #
    def _eval(self, node):
        kind = node[0]
        if kind == "term":
            return self._eval_term(node[1])
        if kind == "prefix":
            return self._eval_prefix(node[1])
        if kind == "phrase":
            return self._eval_phrase(node[1])
        if kind == "and":
            left = self._eval(node[1])
            right = self._eval(node[2])
            common = left.keys() & right.keys()
            return {doc: left[doc] + right[doc] for doc in common}
        if kind == "or":
            merged = self._eval(node[1])
            for doc, score in self._eval(node[2]).items():
                merged[doc] = merged.get(doc, 0.0) + score
            return merged
        if kind == "not":
            excluded = self._eval(node[1])
            return {
                doc: 0.0
                for doc in self.index.doc_ids()
                if doc not in excluded
            }
        raise SearchError("unknown query node: %r" % (kind,))

    def _eval_term(self, word):
        tokens = self.tokenizer.tokenize(word)
        if not tokens:
            # stop-word-only or unmatchable term: matches nothing
            return {}
        merged = {}
        for term in tokens:
            for doc, score in self.scorer.term_scores(term).items():
                merged[doc] = merged.get(doc, 0.0) + score
        return merged

    def _eval_prefix(self, prefix):
        prefix = prefix.lower()
        merged = {}
        for term in self.index.vocabulary():
            if term.startswith(prefix):
                for doc, score in self.scorer.term_scores(term).items():
                    merged[doc] = merged.get(doc, 0.0) + score
        return merged

    def _eval_phrase(self, text):
        terms = self.tokenizer.tokenize(text)
        if not terms:
            raise SearchError("phrase contains no searchable terms")
        if len(terms) == 1:
            return self.scorer.term_scores(terms[0])
        postings = []
        for term in terms:
            term_postings = self.index.postings.get(term)
            if not term_postings:
                return {}
            postings.append(term_postings)
        common = set(postings[0])
        for term_postings in postings[1:]:
            common &= set(term_postings)
        idf_sum = sum(
            self.scorer.idf(self.index.document_frequency(t)) for t in set(terms)
        )
        scores = {}
        for doc in common:
            position_sets = [set(p[doc]) for p in postings]
            count = sum(
                1
                for start in position_sets[0]
                if all(start + offset in position_sets[offset]
                       for offset in range(1, len(terms)))
            )
            if count:
                scores[doc] = (1 + math.log(count)) * idf_sum
        return scores
