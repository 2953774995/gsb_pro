"""JSON persistence for the inverted index and synonym configuration."""
from __future__ import annotations

import json
import os
import tempfile
from typing import Tuple

from .index import InvertedIndex
from .synonyms import SynonymStore
from .tokenizer import Analyzer

INDEX_VERSION = 2


def save_index(path: str, index: InvertedIndex,
               synonyms: SynonymStore) -> None:
    payload = {
        "version": INDEX_VERSION,
        "settings": {
            "use_stopwords": index.analyzer.use_stopwords,
        },
        "documents": {
            _key_to_json(doc_id): record
            for doc_id, record in index.documents.items()
        },
        "doc_lengths": {
            _key_to_json(doc_id): length
            for doc_id, length in index.doc_lengths.items()
        },
        "postings": {
            term: {_key_to_json(doc_id): posting
                   for doc_id, posting in docs.items()}
            for term, docs in index.postings.items()
        },
        "stop_positions": {
            _key_to_json(doc_id): positions
            for doc_id, positions in index.doc_stop_positions.items()
            if positions
        },
        "synonyms": synonyms.to_dict() if synonyms is not None else {"groups": []},
    }
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".kbsearch-", suffix=".tmp",
                                    dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _key_to_json(doc_id) -> str:
    if isinstance(doc_id, bool) or not isinstance(doc_id, (int, str)):
        raise TypeError("doc_id must be int or str")
    marker = "i" if isinstance(doc_id, int) else "s"
    # Unit separator makes "i:1" distinct from a literal string id "1".
    return marker + "\x1f" + str(doc_id)


def _key_from_json(value: str):
    try:
        marker, raw = str(value).split("\x1f", 1)
    except ValueError:
        raise ValueError("Invalid doc_id key in index file")
    if marker == "i":
        try:
            return int(raw)
        except ValueError:
            raise ValueError("Invalid integer doc_id in index file")
    if marker == "s":
        return raw
    raise ValueError("Invalid doc_id marker in index file")


def load_index(path: str) -> Tuple[InvertedIndex, SynonymStore]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    version = payload.get("version")
    if version != INDEX_VERSION:
        raise ValueError("Unsupported kbsearch index version: %r" % version)

    settings = payload.get("settings", {})
    analyzer = Analyzer(use_stopwords=bool(settings.get("use_stopwords", True)))
    index = InvertedIndex(analyzer)
    index.documents = payload.get("documents", {})
    # JSON object keys are strings; normalize all persisted doc ids.
    index.documents = {_key_from_json(key): value
                       for key, value in index.documents.items()}
    index.doc_lengths = {
        _key_from_json(key): int(value)
        for key, value in payload.get("doc_lengths", {}).items()
    }
    index.postings = {}
    doc_terms = {doc_id: [] for doc_id in index.documents}
    for term, docs in payload.get("postings", {}).items():
        index.postings[term] = {}
        for key, posting in docs.items():
            doc_id = _key_from_json(key)
            index.postings[term][doc_id] = {
                "tf": int(posting.get("tf", 0)),
                "positions": [int(p) for p in posting.get("positions", [])],
            }
            doc_terms.setdefault(doc_id, []).append(term)
    index.doc_terms = doc_terms
    index.doc_stop_positions = {
        _key_from_json(key): {
            term: [int(position) for position in positions]
            for term, positions in docs.items()
        }
        for key, docs in payload.get("stop_positions", {}).items()
    }
    index._cache_dirty = True
    synonyms = SynonymStore.from_dict(payload.get("synonyms", {}), analyzer)
    return index, synonyms
