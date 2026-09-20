"""Tokenization, normalization and text spans."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, List, Set, Tuple

from .stemmer import stem

# A compact but useful English stop-word list.  Chinese is indexed by
# character and therefore does not need a Chinese stop list.
DEFAULT_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for",
    "if", "in", "into", "is", "it", "no", "not", "of", "on", "or", "such",
    "that", "the", "their", "then", "there", "these", "they", "this", "to",
    "was", "will", "with",
})

_ASCII_RUN = 0
_CJK_RANGES = (
    (0x3400, 0x4DBF),    # CJK Extension A
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0xF900, 0xFAFF),    # CJK Compatibility Ideographs
    (0x20000, 0x2A6DF),  # Extension B
    (0x2A700, 0x2B73F),  # Extension C
)


def is_cjk_char(ch: str) -> bool:
    code = ord(ch)
    return any(start <= code <= end for start, end in _CJK_RANGES)


@dataclass(frozen=True)
class Token:
    """One indexed term and its raw-text span."""
    term: str
    position: int
    start: int
    end: int


class Analyzer:
    """Tokenizes mixed English/Chinese text and applies index normalization."""

    def __init__(self, use_stopwords: bool = True,
                 stopwords: Set[str] = None) -> None:
        self.use_stopwords = use_stopwords
        words = set(DEFAULT_STOPWORDS if stopwords is None else stopwords)
        # Stop words are compared after stemming/lower-casing.
        self.stopwords = frozenset(stem(w) for w in words)

    def _raw_runs(self, text: str) -> Iterator[Tuple[str, int, int]]:
        start = None
        kind = None
        for i, ch in enumerate(text):
            if ch.isascii() and (ch.isalpha() or ch.isdigit()):
                char_kind = _ASCII_RUN
            elif is_cjk_char(ch):
                # Every CJK ideograph is its own token.  Emit a pending
                # English/number run before it.
                char_kind = ord(ch)
            else:
                char_kind = None
            if char_kind is None:
                if start is not None:
                    yield text[start:i], start, i
                    start = None
                    kind = None
                continue
            if char_kind == _ASCII_RUN:
                if start is None or kind != _ASCII_RUN:
                    if start is not None:
                        yield text[start:i], start, i
                    start = i
                    kind = _ASCII_RUN
            else:
                if start is not None:
                    yield text[start:i], start, i
                yield ch, i, i + 1
                start = None
                kind = None
        if start is not None:
            yield text[start:len(text)], start, len(text)

    def _normalize_run(self, run: str) -> str:
        lowered = run.lower()
        if lowered.isascii() and lowered.isalnum():
            return stem(lowered)
        # A run emitted by _raw_runs is normally one CJK character, but keep
        # this defensive branch for readable behavior.
        return lowered

    def tokenize_all(self, text: str) -> List[Token]:
        """Return all meaningful tokens, including configured stop words."""
        tokens = []
        for position, (run, start, end) in enumerate(self._raw_runs(text)):
            term = self._normalize_run(run)
            if not term:
                continue
            tokens.append(Token(term=term, position=position, start=start, end=end))
        return tokens

    def analyze(self, text: str) -> List[Token]:
        """Return searchable tokens with dense positions.

        Stop words are removed from searchable postings when
        ``use_stopwords`` is true.  Token positions intentionally retain the
        original raw-token ordinal; stop-word positions are stored separately
        by the index for quoted-phrase adjacency.
        """
        return [token for token in self.tokenize_all(text)
                if not (self.use_stopwords and token.term in self.stopwords)]

    def is_stop_term(self, term: str) -> bool:
        return bool(self.use_stopwords and term in self.stopwords)
