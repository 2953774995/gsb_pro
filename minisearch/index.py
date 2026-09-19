"""In-memory inverted index: term -> {doc_id: [positions]}."""


class InvertedIndex:
    def __init__(self):
        self.postings = {}      # term -> {doc_id: [position, ...]}
        self.doc_lengths = {}   # doc_id -> number of indexed tokens
        self.documents = {}     # doc_id -> raw text (for snippets)
        self._doc_terms = {}    # doc_id -> set of terms (for clean removal)

    def document_count(self):
        return len(self.documents)

    def __contains__(self, doc_id):
        return doc_id in self.documents

    def add_document(self, doc_id, tokens, text):
        """Index a document; an existing doc_id is fully replaced."""
        if doc_id in self.documents:
            self.remove_document(doc_id)
        term_positions = {}
        for position, term in enumerate(tokens):
            term_positions.setdefault(term, []).append(position)
        for term, positions in term_positions.items():
            self.postings.setdefault(term, {})[doc_id] = positions
        self._doc_terms[doc_id] = set(term_positions)
        self.doc_lengths[doc_id] = len(tokens)
        self.documents[doc_id] = text

    def remove_document(self, doc_id):
        """Remove every posting of the document, leaving no residue."""
        terms = self._doc_terms.pop(doc_id, None)
        if terms is None:
            return False
        for term in terms:
            term_postings = self.postings[term]
            del term_postings[doc_id]
            if not term_postings:
                del self.postings[term]
        del self.doc_lengths[doc_id]
        del self.documents[doc_id]
        return True

    def document_frequency(self, term):
        return len(self.postings.get(term, ()))

    def vocabulary(self):
        return self.postings.keys()

    def doc_ids(self):
        return self.documents.keys()
