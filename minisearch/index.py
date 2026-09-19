"""In-memory inverted index: term -> {doc_id: (tf, [positions])}.

Also tracks document frequency (df) per term and the effective token
count (document length) per document. Removal fully cleans up every
posting of the document, leaving no intermediate state behind.
"""


class Posting:
    __slots__ = ("tf", "positions")

    def __init__(self):
        self.tf = 0
        self.positions = []


class InvertedIndex:
    def __init__(self):
        self._postings = {}       # term -> {doc_id: Posting}
        self._doc_lengths = {}    # doc_id -> effective token count
        self._doc_terms = {}      # doc_id -> set of terms (for clean removal)

    @property
    def document_count(self):
        return len(self._doc_lengths)

    @property
    def vocabulary(self):
        return self._postings.keys()

    def add_document(self, doc_id, tokens):
        """Index a document from a list of (term, position) pairs.

        Re-adding an existing doc_id replaces the old document.
        """
        if doc_id in self._doc_lengths:
            self.remove_document(doc_id)
        terms = set()
        for term, position in tokens:
            terms.add(term)
            doc_postings = self._postings.setdefault(term, {})
            posting = doc_postings.get(doc_id)
            if posting is None:
                posting = Posting()
                doc_postings[doc_id] = posting
            posting.tf += 1
            posting.positions.append(position)
        self._doc_lengths[doc_id] = len(tokens)
        self._doc_terms[doc_id] = terms

    def remove_document(self, doc_id):
        """Remove a document and all of its postings. Returns True if removed."""
        terms = self._doc_terms.pop(doc_id, None)
        if terms is None:
            return False
        for term in terms:
            doc_postings = self._postings[term]
            del doc_postings[doc_id]
            if not doc_postings:
                del self._postings[term]
        del self._doc_lengths[doc_id]
        return True

    def get_posting(self, term, doc_id):
        doc_postings = self._postings.get(term)
        if doc_postings is None:
            return None
        return doc_postings.get(doc_id)

    def get_postings(self, term):
        """Return {doc_id: Posting} for a term (empty dict if unknown)."""
        return self._postings.get(term, {})

    def document_frequency(self, term):
        return len(self._postings.get(term, ()))

    def doc_length(self, doc_id):
        return self._doc_lengths.get(doc_id, 0)

    def average_doc_length(self):
        if not self._doc_lengths:
            return 0.0
        return sum(self._doc_lengths.values()) / len(self._doc_lengths)

    def doc_ids(self):
        return set(self._doc_lengths)

    def terms_with_prefix(self, prefix):
        return [term for term in self._postings if term.startswith(prefix)]
