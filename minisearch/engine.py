"""SearchEngine: the public API tying tokenizer, index, parser and scorer."""

from .index import InvertedIndex
from .query import And, Not, Or, Phrase, Prefix, Term, SearchError, parse_query
from .scorer import evaluate
from .snippet import generate_snippet
from .tokenizer import DEFAULT_STOP_WORDS, tokenize

__all__ = ["SearchEngine", "SearchError"]


def _collect_raw_terms(node, out):
    if isinstance(node, Term):
        out.append(node.raw)
    elif isinstance(node, Phrase):
        out.extend(node.raw_terms)
    elif isinstance(node, Prefix):
        out.append(node.prefix)
    elif isinstance(node, (And, Or)):
        for child in node.children:
            _collect_raw_terms(child, out)
    elif isinstance(node, Not):
        pass  # negated terms should not drive snippet highlights


class SearchEngine:
    def __init__(self, use_stop_words=True, stem=True, stop_words=None):
        self.use_stop_words = use_stop_words
        self.stem = stem
        self.stop_words = DEFAULT_STOP_WORDS if stop_words is None else stop_words
        self._index = InvertedIndex()
        self._documents = {}

    def add_document(self, doc_id, text):
        """Add or replace a document. doc_id may be an int or a str."""
        if not isinstance(doc_id, (int, str)) or isinstance(doc_id, bool):
            raise TypeError("doc_id must be an int or a str")
        if not isinstance(text, str):
            raise TypeError("text must be a str")
        tokens = tokenize(text, use_stop_words=self.use_stop_words,
                          stop_words=self.stop_words, stem=self.stem)
        self._index.add_document(doc_id, tokens)
        self._documents[doc_id] = text

    def remove_document(self, doc_id):
        """Remove a document and all of its index state. Returns success."""
        removed = self._index.remove_document(doc_id)
        self._documents.pop(doc_id, None)
        return removed

    def document_count(self):
        return self._index.document_count

    def search(self, query, top_k=10, with_snippet=False):
        """Run a query. Returns an ordered list of result dicts.

        Each result has keys "doc_id" and "score", plus "snippet" when
        with_snippet=True. top_k=0 returns all matches.
        """
        if top_k < 0:
            raise SearchError("top_k must be >= 0")
        ast = parse_query(query, use_stop_words=self.use_stop_words,
                          stop_words=self.stop_words, stem=self.stem)
        if self._index.document_count == 0:
            return []
        scores = evaluate(ast, self._index)
        ordered = sorted(scores.items(),
                         key=lambda item: (-item[1], str(item[0])))
        if top_k > 0:
            ordered = ordered[:top_k]
        raw_terms = []
        if with_snippet:
            _collect_raw_terms(ast, raw_terms)
        results = []
        for doc_id, score in ordered:
            result = {"doc_id": doc_id, "score": score}
            if with_snippet:
                result["snippet"] = generate_snippet(
                    self._documents.get(doc_id, ""), raw_terms)
            results.append(result)
        return results
