"""In-memory inverted index and document store."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

from .tokenizer import Analyzer


class InvertedIndex:
    """Term dictionary, postings and per-document length statistics."""

    def __init__(self, analyzer: Optional[Analyzer] = None) -> None:
        self.analyzer = analyzer or Analyzer()
        # term -> {doc_id: {"tf": int, "positions": [int]}}
        self.postings: Dict[str, Dict[object, dict]] = defaultdict(dict)
        # doc_id -> text supplied by the caller
        self.documents: Dict[object, dict] = {}
        # doc_id -> number of retained terms (valid length for scoring).
        self.doc_lengths: Dict[object, int] = {}
        # Reverse list used for O(unique terms in doc) deletion.
        self.doc_terms: Dict[object, List[str]] = {}
        # Positions of configured English stop words.  They do not participate
        # in the searchable postings/df, but are retained so a quoted phrase
        # can validate adjacency across words such as "does not cool".
        self.doc_stop_positions: Dict[object, Dict[str, List[int]]] = {}
        # Cache of term idf values; invalidated whenever the index changes.
        self._idf_cache: Dict[str, float] = {}
        self._cache_dirty = True

    def set_analyzer(self, analyzer: Analyzer) -> None:
        self.analyzer = analyzer
        # Existing postings stay in the old normalization.  This method is
        # mainly used while loading a complete persisted index.
        self._cache_dirty = True

    def add_document(self, doc_id: object, text: str,
                     title: str = "", source: str = None,
                     extra: dict = None) -> None:
        """Overwrite an existing document atomically from the caller's view."""
        self.remove_document(doc_id)
        all_tokens = self.analyzer.tokenize_all(text)
        tokens = [token for token in all_tokens
                  if not self.analyzer.is_stop_term(token.term)]
        by_term: Dict[str, dict] = {}
        stop_positions: Dict[str, List[int]] = {}
        for token in all_tokens:
            if self.analyzer.is_stop_term(token.term):
                stop_positions.setdefault(token.term, []).append(token.position)
                continue
            entry = by_term.get(token.term)
            if entry is None:
                entry = {"tf": 0, "positions": []}
                by_term[token.term] = entry
            entry["tf"] += 1
            entry["positions"].append(token.position)

        for term, data in by_term.items():
            self.postings.setdefault(term, {})[doc_id] = data
        record = {"text": text, "title": title, "source": source}
        if extra:
            for key, value in extra.items():
                if key not in record:
                    record[key] = value
        self.documents[doc_id] = record
        self.doc_lengths[doc_id] = len(tokens)
        self.doc_terms[doc_id] = list(by_term)
        self.doc_stop_positions[doc_id] = stop_positions
        self._cache_dirty = True

    def remove_document(self, doc_id: object) -> bool:
        """Remove every posting belonging to ``doc_id``."""
        existed = doc_id in self.documents
        for term in self.doc_terms.pop(doc_id, []):
            docs = self.postings.get(term)
            if docs is not None and doc_id in docs:
                del docs[doc_id]
                if not docs:
                    del self.postings[term]
        self.documents.pop(doc_id, None)
        self.doc_lengths.pop(doc_id, None)
        self.doc_stop_positions.pop(doc_id, None)
        if existed:
            self._cache_dirty = True
        return existed

    def document_count(self) -> int:
        return len(self.documents)

    def get_text(self, doc_id: object) -> Optional[str]:
        record = self.documents.get(doc_id)
        return None if record is None else record.get("text", "")

    def get_record(self, doc_id: object) -> Optional[dict]:
        return self.documents.get(doc_id)

    def document_frequency(self, term: str) -> int:
        return len(self.postings.get(term, ()))

    def term_frequency(self, term: str, doc_id: object) -> int:
        entry = self.postings.get(term, {}).get(doc_id)
        return 0 if entry is None else int(entry["tf"])

    def positions(self, term: str, doc_id: object) -> Tuple[int, ...]:
        entry = self.postings.get(term, {}).get(doc_id)
        return tuple(entry.get("positions", ())) if entry else tuple()

    def positions_for_phrase(self, term: str, doc_id: object) -> Tuple[int, ...]:
        """Return searchable-term or stop-word positions for phrase checks."""
        positions = self.positions(term, doc_id)
        if positions:
            return positions
        return tuple(self.doc_stop_positions.get(doc_id, {}).get(term, ()))

    def docs_for_term(self, term: str) -> Iterable[object]:
        return self.postings.get(term, {}).keys()

    def terms_with_prefix(self, prefix: str) -> List[str]:
        # Dictionary iteration is still required by a prefix query, but it is
        # read-only and avoids expanding terms that occur in no document.
        return sorted(term for term in self.postings if term.startswith(prefix))

    def idf(self, term: str) -> float:
        if self._cache_dirty:
            self._idf_cache = {}
            self._cache_dirty = False
        value = self._idf_cache.get(term)
        if value is None:
            import math
            df = self.document_frequency(term)
            n = self.document_count()
            value = math.log1p(n / df) if df else 0.0
            self._idf_cache[term] = value
        return value

    def term_weight(self, term: str, doc_id: object) -> float:
        tf = self.term_frequency(term, doc_id)
        if tf <= 0:
            return 0.0
        return (1.0 + math.log(tf)) * self.idf(term)
