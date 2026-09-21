"""Tokenization, normalization, stemming and stop-word handling.

Rules (documented in README.md):

* English / numeric runs (``[a-zA-Z0-9]+``) become one token, lowercased.
* A simplified suffix-stripping stemmer is applied to ASCII words:
  ``ing`` (len>4), ``ed``/``ly`` (len>3) are stripped; plurals follow
  Porter step 1a (``sses``->``ss``, ``ies``->``i``, ``ss`` kept, else a
  trailing ``s`` is stripped). At most one rule fires. See ``stem()``.
* Every CJK character becomes a token of its own (unigram indexing), so any
  Chinese query string can be matched positionally.
* A built-in English stop-word list can be enabled/disabled.
"""

import re

#: Common English stop words.
STOPWORDS = frozenset(
    """
    a an the is are was were be been being of to in on for and or not no
    with by at from as it its this that these those i you he she we they
    do does did have has had will would can could shall should may might
    """.split()
)

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[一-鿿㐀-䶿]")


def stem(word):
    """Simplified suffix-stripping stemmer for lowercase ASCII words.

    Rules (applied in order, at most one fires):
    ``ing`` (len>4), ``ed``/``ly`` (len>3) are stripped; plurals follow
    Porter step 1a: ``sses``->``ss``, ``ies``->``i``, ``ss`` kept,
    otherwise a trailing ``s`` (len>2) is stripped.
    """
    w = word.lower()
    if len(w) > 4 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 3 and w.endswith("ed"):
        return w[:-2]
    if len(w) > 3 and w.endswith("ly"):
        return w[:-2]
    if w.endswith("sses"):
        return w[:-2]
    if len(w) > 3 and w.endswith("ies"):
        return w[:-2]
    if w.endswith("ss"):
        return w
    if len(w) > 2 and w.endswith("s"):
        return w[:-1]
    return w


class Tokenizer:
    """Splits text into normalized tokens."""

    def __init__(self, use_stopwords=True):
        self.use_stopwords = use_stopwords

    def _normalize(self, raw):
        if raw.isascii():
            w = stem(raw)
            if self.use_stopwords and w in STOPWORDS:
                return None
            # stop-word check must happen on the unstemmed surface form too
            if self.use_stopwords and raw.lower() in STOPWORDS:
                return None
            return w
        # CJK character: indexed as-is (unigram)
        return raw

    def tokenize(self, text):
        """Return the list of normalized tokens for *text*."""
        return [t for t, _, _ in self.tokenize_with_spans(text)]

    def tokenize_with_spans(self, text):
        """Return ``[(token, start, end), ...]`` with char offsets in *text*."""
        out = []
        for m in _TOKEN_RE.finditer(text):
            tok = self._normalize(m.group(0))
            if tok is not None:
                out.append((tok, m.start(), m.end()))
        return out
