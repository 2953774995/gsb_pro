"""JSON persistence for the inverted index.

File layout (UTF-8 JSON)::

    {
      "version": 1,
      "use_stopwords": true,
      "doc_lengths": {"i:42": 10, "s:manual-a": 25},
      "doc_texts":   {"i:42": "...", ...},
      "doc_meta":    {"i:42": {"source": "...", "title": "...", "mtime": 0.0}},
      "postings":    {"term": {"i:42": [tf, [pos, ...]], ...}, ...}
    }

Document ids keep their type: ``i:`` prefix = int, ``s:`` prefix = str.
"""

import json

from .index import InvertedIndex

FORMAT_VERSION = 1


def encode_doc_id(doc_id):
    if isinstance(doc_id, int) and not isinstance(doc_id, bool):
        return "i:%d" % doc_id
    return "s:%s" % doc_id


def decode_doc_id(key):
    if key.startswith("i:"):
        return int(key[2:])
    return key[2:]


def save_index(index, path, use_stopwords=True):
    data = {
        "version": FORMAT_VERSION,
        "use_stopwords": use_stopwords,
        "doc_lengths": {encode_doc_id(d): n for d, n in index.doc_lengths.items()},
        "doc_texts": {encode_doc_id(d): t for d, t in index.doc_texts.items()},
        "doc_meta": {encode_doc_id(d): m for d, m in index.doc_meta.items()},
        "postings": {
            term: {encode_doc_id(d): [tf, positions] for d, (tf, positions) in posting.items()}
            for term, posting in index.postings.items()
        },
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)


def load_index(path):
    """Return ``(InvertedIndex, meta_dict)`` loaded from *path*."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("version") != FORMAT_VERSION:
        raise ValueError("unsupported index format version: %r" % (data.get("version"),))
    index = InvertedIndex()
    index.doc_lengths = {decode_doc_id(k): v for k, v in data["doc_lengths"].items()}
    index.doc_texts = {decode_doc_id(k): v for k, v in data.get("doc_texts", {}).items()}
    index.doc_meta = {decode_doc_id(k): v for k, v in data.get("doc_meta", {}).items()}
    index.postings = {
        term: {decode_doc_id(k): [v[0], list(v[1])] for k, v in posting.items()}
        for term, posting in data["postings"].items()
    }
    meta = {"use_stopwords": data.get("use_stopwords", True)}
    return index, meta
