"""Tokenization, normalization, stop-word filtering and simple stemming.

English tokens: maximal runs of ASCII letters/digits, lowercased.
Chinese tokens: each CJK character becomes its own token (unigram indexing),
so any Chinese query term can match.
Positions are token indexes within the document, used for phrase queries.
"""

import re

DEFAULT_STOP_WORDS = frozenset([
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "of", "in", "on", "at", "to", "for", "with", "by", "from",
    "and", "or", "not", "but", "if", "then", "else", "so",
    "as", "it", "its", "this", "that", "these", "those",
    "i", "you", "he", "she", "we", "they", "them", "his", "her", "their",
    "do", "does", "did", "have", "has", "had",
    "will", "would", "can", "could", "shall", "should", "may", "might", "must",
])

_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_CJK_RE = re.compile(
    "[一-鿿㐀-䶿豈-﫿]"
)


def _is_cjk(char):
    return _CJK_RE.match(char) is not None


def simple_stem(word):
    """A deliberately small, deterministic suffix-stripping stemmer.

    Rules (applied in order, at most one rule fires per word):
      - ies -> y        (cities -> city), word length > 4
      - es  -> ''       (boxes -> box), only after s/x/z/ch/sh, length > 3
      - s   -> ''       (cats -> cat), not after s/u, length > 3
      - ing -> ''       (running -> runn -> run via double-consonant fix), length > 5
      - ed  -> ''       (walked -> walk), length > 4
    Double trailing consonants left by ing/ed stripping are collapsed
    (running -> run, stopped -> stop). This is an intentionally simplified
    Porter-style rule set; see README for details.
    """
    if len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("es") and len(word) > 3:
        stem = word[:-2]
        if stem.endswith(("s", "x", "z", "ch", "sh")):
            return stem
    if word.endswith("s") and not word.endswith(("ss", "us", "is")) and len(word) > 3:
        return word[:-1]
    for suffix, min_len in (("ing", 5), ("ed", 4)):
        if word.endswith(suffix) and len(word) > min_len:
            stem = word[: -len(suffix)]
            if len(stem) >= 2 and stem[-1] == stem[-2] and stem[-1] not in "aeiou":
                stem = stem[:-1]
            return stem
    return word


def tokenize(text, use_stop_words=True, stop_words=None, stem=True):
    """Split text into a list of normalized tokens (position order preserved).

    Returns a list of (term, position) pairs.
    """
    if stop_words is None:
        stop_words = DEFAULT_STOP_WORDS
    tokens = []
    position = 0
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if _is_cjk(char):
            tokens.append((char, position))
            position += 1
            index += 1
            continue
        match = _WORD_RE.match(text, index)
        if match:
            word = match.group(0).lower()
            index = match.end()
            if use_stop_words and word in stop_words:
                continue
            if stem:
                word = simple_stem(word)
            tokens.append((word, position))
            position += 1
            continue
        index += 1
    return tokens
