"""Tokenization, normalization, stop-word filtering and light stemming.

English tokens are maximal runs of ASCII letters/digits, lowercased and
stemmed with a small Porter-like rule set.  Every CJK ideograph is indexed
as its own single-character token so any Chinese query term can match.
"""

import re

TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[㐀-䶿一-鿿]")

DEFAULT_STOPWORDS = frozenset(
    """
    a an the is are was were be been being of to in on for and or not no
    it its this that these those with as at by from but if then so such
    """.split()
)


def _has_vowel(word):
    return any(ch in "aeiou" for ch in word)


def stem(word):
    """Simplified Porter-style stemming.

    Rules (applied in order, first match wins):
      1. ``ies`` -> ``y``            (studies -> study)
      2. drop ``ing`` / ``ed`` when the remaining stem has >= 3 chars and a
         vowel; collapse a trailing double consonant (running -> run)
      3. drop a trailing ``s`` unless the word ends in ss/us/is (cats -> cat);
         words ending in s/x/z + ``es`` lose both letters (foxes -> fox)
    Words of length <= 2 are returned unchanged.
    """
    if len(word) <= 2:
        return word
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    for suffix in ("ing", "ed"):
        if word.endswith(suffix):
            base = word[: -len(suffix)]
            if len(base) >= 3 and _has_vowel(base):
                if (
                    len(base) >= 2
                    and base[-1] == base[-2]
                    and base[-1] not in "aeiou"
                ):
                    base = base[:-1]
                return base
    if (
        len(word) > 3
        and word.endswith("s")
        and not word.endswith(("ss", "us", "is"))
    ):
        if word.endswith("es") and (word[-3] in "sxz" or word.endswith(("ches", "shes"))):
            return word[:-2]
        return word[:-1]
    return word


def is_cjk(token):
    return all("㐀" <= ch <= "䶿" or "一" <= ch <= "鿿" for ch in token)


class Tokenizer:
    """Splits raw text into normalized tokens.

    Positions are assigned *after* stop-word removal, so phrases match
    regardless of stop words inside them (e.g. "state of the art" matches
    the phrase "state art").
    """

    def __init__(self, use_stopwords=True, stopwords=None):
        self.use_stopwords = use_stopwords
        self.stopwords = DEFAULT_STOPWORDS if stopwords is None else frozenset(stopwords)

    def tokenize(self, text):
        """Return the list of normalized tokens in document order."""
        tokens = []
        for match in TOKEN_RE.finditer(text.lower()):
            raw = match.group(0)
            if is_cjk(raw):
                tokens.append(raw)
                continue
            if self.use_stopwords and raw in self.stopwords:
                continue
            term = stem(raw)
            if term:
                tokens.append(term)
        return tokens
