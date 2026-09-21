"""In-memory inverted index.

Structures maintained:

* ``postings``: ``term -> {doc_id: [tf, [positions]]}``
* ``doc_lengths``: ``doc_id -> number of valid tokens`` (document length)
* ``doc_texts``: ``doc_id -> raw text`` (used for snippet generation so the
  index is self-contained after a reload)
* ``doc_meta``: ``doc_id -> dict`` (source path, title, mtime ...)

``df`` of a term is ``len(postings[term])``; terms whose posting map becomes
empty are removed, so deletions leave no residue.
"""


class InvertedIndex:
    def __init__(self):
        self.postings = {}
        self.doc_lengths = {}
        self.doc_texts = {}
        self.doc_meta = {}

    # ------------------------------------------------------------------ #
    @property
    def doc_count(self):
        return len(self.doc_lengths)

    @property
    def doc_ids(self):
        return set(self.doc_lengths)

    def df(self, term):
        posting = self.postings.get(term)
        return len(posting) if posting else 0

    # ------------------------------------------------------------------ #
    def add_document(self, doc_id, tokens, text="", meta=None):
        """Add a document; an existing *doc_id* is overwritten."""
        if doc_id in self.doc_lengths:
            self.remove_document(doc_id)
        counts = {}
        positions = {}
        for pos, tok in enumerate(tokens):
            counts[tok] = counts.get(tok, 0) + 1
            positions.setdefault(tok, []).append(pos)
        for tok, tf in counts.items():
            self.postings.setdefault(tok, {})[doc_id] = [tf, positions[tok]]
        self.doc_lengths[doc_id] = len(tokens)
        self.doc_texts[doc_id] = text
        self.doc_meta[doc_id] = dict(meta or {})

    def remove_document(self, doc_id):
        """Remove every posting of *doc_id*. Unknown ids are ignored."""
        if doc_id not in self.doc_lengths:
            return
        empty_terms = []
        for term, posting in self.postings.items():
            if doc_id in posting:
                del posting[doc_id]
                if not posting:
                    empty_terms.append(term)
        for term in empty_terms:
            del self.postings[term]
        del self.doc_lengths[doc_id]
        del self.doc_texts[doc_id]
        del self.doc_meta[doc_id]
