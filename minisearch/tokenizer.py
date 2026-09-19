"""Tokenization and normalization for mixed Chinese/English text.

Rules
-----
* English / numeric runs (``[A-Za-z0-9]+``) become one token, lowercased,
  optionally stopword-filtered and stemmed.
* Every CJK ideograph becomes a single-character token (character-level
  indexing), which guarantees any Chinese query string can match.
* Positions count every raw token of the original stream (including removed
  stopwords), so phrase queries keep correct adjacency semantics.
"""

import re

from .stemmer import stem

_CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[㐀-䶿一-鿿豈-﫿]")


def tokenize(text, stopwords=None, stemmer=stem):
    """Split *text* into a list of ``(term, position)`` tuples.

    ``stopwords`` is a set of lowercase terms to drop (``None`` disables
    filtering).  ``stemmer`` is a callable applied to non-CJK tokens
    (``None`` disables stemming).
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    tokens = []
    position = 0
    for match in _TOKEN_RE.finditer(text):
        raw = match.group(0)
        pos = position
        position += 1
        if _CJK_RE.fullmatch(raw):
            tokens.append((raw, pos))
            continue
        term = raw.lower()
        if stopwords is not None and term in stopwords:
            continue
        if stemmer is not None:
            term = stemmer(term)
        if not term:
            continue
        tokens.append((term, pos))
    return tokens


def terms(text, stopwords=None, stemmer=stem):
    """Convenience wrapper returning only the term strings."""
    return [t for t, _ in tokenize(text, stopwords=stopwords, stemmer=stemmer)]
