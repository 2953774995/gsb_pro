"""In-memory inverted index.

Structure
---------
* ``_postings``:    term -> {doc_id: [positions]}   (tf = len(positions))
* ``_doc_lengths``: doc_id -> number of indexed tokens ("有效词数")
* ``_doc_terms``:   doc_id -> set of distinct terms (used for clean removal)

``df(term)`` is derived from the postings map, so it can never drift out of
sync with the postings themselves.
"""


class InvertedIndex:
    def __init__(self):
        self._postings = {}
        self._doc_lengths = {}
        self._doc_terms = {}

    # ------------------------------------------------------------------ #
    # mutation
    # ------------------------------------------------------------------ #
    def add_document(self, doc_id, tokens):
        """Index ``tokens`` (list of ``(term, position)``) under ``doc_id``.

        Re-adding an existing ``doc_id`` atomically replaces the old
        document: its postings are removed first, so no stale state remains.
        """
        if doc_id in self._doc_terms:
            self.remove_document(doc_id)
        per_doc = {}
        for term, pos in tokens:
            per_doc.setdefault(term, []).append(pos)
        for term, positions in per_doc.items():
            self._postings.setdefault(term, {})[doc_id] = positions
        self._doc_terms[doc_id] = set(per_doc)
        self._doc_lengths[doc_id] = len(tokens)

    def remove_document(self, doc_id):
        """Remove every posting of ``doc_id``.  Returns True if it existed."""
        terms = self._doc_terms.pop(doc_id, None)
        if terms is None:
            return False
        for term in terms:
            docs = self._postings.get(term)
            if docs is None:
                continue
            docs.pop(doc_id, None)
            if not docs:
                del self._postings[term]
        self._doc_lengths.pop(doc_id, None)
        return True

    # ------------------------------------------------------------------ #
    # accessors
    # ------------------------------------------------------------------ #
    def postings(self, term):
        """Return ``{doc_id: [positions]}`` for *term* (empty dict if none)."""
        return self._postings.get(term, {})

    def df(self, term):
        """Document frequency of *term*."""
        return len(self._postings.get(term, ()))

    def doc_length(self, doc_id):
        """Number of indexed tokens of *doc_id* (0 if unknown)."""
        return self._doc_lengths.get(doc_id, 0)

    @property
    def document_count(self):
        return len(self._doc_lengths)

    def doc_ids(self):
        return list(self._doc_lengths)

    def vocabulary(self):
        return set(self._postings)

    def terms_with_prefix(self, prefix):
        """All dictionary terms starting with *prefix* (sorted)."""
        return sorted(t for t in self._postings if t.startswith(prefix))
