"""KBSearch: the public facade tying all components together."""

from .query import Evaluator, parse_query
from .snippet import make_snippet
from .storage import load_index, save_index
from .synonyms import SynonymMap
from .tokenizer import Tokenizer


class KBSearch:
    """Offline full-text search over a small document collection.

    Parameters
    ----------
    use_stopwords:
        Filter the built-in English stop-word list (default ``True``).
    synonyms:
        A :class:`SynonymMap` used to expand bare query terms.
    """

    def __init__(self, use_stopwords=True, synonyms=None):
        self.tokenizer = Tokenizer(use_stopwords=use_stopwords)
        self.use_stopwords = use_stopwords
        self.synonyms = synonyms if synonyms is not None else SynonymMap()
        from .index import InvertedIndex

        self.index = InvertedIndex()

    # ------------------------------------------------------------------ #
    # document management
    # ------------------------------------------------------------------ #
    def add_document(self, doc_id, text, meta=None):
        """Add a document; re-adding the same *doc_id* overwrites it.

        *doc_id* may be an ``int`` or a ``str``; *text* may mix Chinese and
        English.
        """
        if not isinstance(doc_id, (int, str)) or isinstance(doc_id, bool):
            raise TypeError("doc_id must be int or str, got %r" % type(doc_id))
        tokens = self.tokenizer.tokenize(text)
        self.index.add_document(doc_id, tokens, text=text, meta=meta)

    def remove_document(self, doc_id):
        """Remove a document and all of its postings (no residue)."""
        self.index.remove_document(doc_id)

    def document_count(self):
        return self.index.doc_count

    # ------------------------------------------------------------------ #
    # synonyms
    # ------------------------------------------------------------------ #
    def load_synonyms(self, path):
        self.synonyms = SynonymMap.from_file(path)

    # ------------------------------------------------------------------ #
    # search
    # ------------------------------------------------------------------ #
    def search(self, query, top_k=10, with_snippet=False):
        """Run *query* and return an ordered list of hits.

        Each hit is ``{"doc_id": ..., "score": ...}`` plus ``"snippet"``
        when *with_snippet* is true. ``top_k=0`` (or ``None``) returns all
        hits. Raises :class:`SearchError` for malformed queries. An empty
        index or a query without matches returns ``[]``.
        """
        ast = parse_query(query, self.tokenizer)
        if self.index.doc_count == 0:
            return []
        evaluator = Evaluator(self.index, self.tokenizer, self.synonyms)
        scores = evaluator.evaluate(ast)
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], str(kv[0])))
        if top_k:
            ranked = ranked[:top_k]
        terms = evaluator.positive_terms(ast) if with_snippet else None
        results = []
        for doc_id, score in ranked:
            hit = {"doc_id": doc_id, "score": score}
            if with_snippet:
                hit["snippet"] = make_snippet(
                    self.index.doc_texts.get(doc_id, ""), terms, self.tokenizer
                )
            results.append(hit)
        return results

    # ------------------------------------------------------------------ #
    # persistence
    # ------------------------------------------------------------------ #
    def save(self, path):
        """Persist the whole index to *path* (JSON)."""
        save_index(self.index, path, use_stopwords=self.use_stopwords)

    @classmethod
    def load(cls, path, synonyms=None, use_stopwords=None):
        """Load a previously saved index; no document rescan needed."""
        index, meta = load_index(path)
        kb = cls(
            use_stopwords=meta["use_stopwords"] if use_stopwords is None else use_stopwords,
            synonyms=synonyms,
        )
        kb.index = index
        return kb
