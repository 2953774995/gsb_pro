"""A simplified Porter-style stemmer (English only).

Rules applied, in order (documented in README.md):

1. Plurals:        ``sses -> ss``, ``ies -> i``, trailing ``s`` removed
                   (words of length <= 3 keep their final ``s``, ``ss`` kept).
2. ``-ed`` / ``-ing`` stripped when the remaining stem has >= 3 characters;
   a trailing double consonant (bb/dd/ff/gg/mm/nn/pp/rr/tt) is then
   collapsed, e.g. ``running -> runn -> run``.
3. ``-ly`` stripped for words longer than 4 characters.

This is a deliberate simplification of the Porter algorithm: it is not a
full implementation, but it behaves identically for the most common English
inflections and is fully deterministic.
"""

_DOUBLE_CONSONANTS = ("bb", "dd", "ff", "gg", "mm", "nn", "pp", "rr", "tt")


def stem(word):
    """Return the stemmed form of a single lowercase alphanumeric token."""
    w = word
    if len(w) <= 2:
        return w

    # Step 1: plurals.
    if w.endswith("sses"):
        w = w[:-2]              # caresses -> caress
    elif w.endswith("ies"):
        w = w[:-2]              # ponies -> poni, studies -> studi
    elif w.endswith("ss"):
        pass                    # caress -> caress
    elif w.endswith("s") and len(w) > 3:
        w = w[:-1]              # cats -> cat

    # Step 2: -ed / -ing.
    for suffix in ("ing", "ed"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[: -len(suffix)]
            if any(w.endswith(dc) for dc in _DOUBLE_CONSONANTS):
                w = w[:-1]      # runn -> run
            break

    # Step 3: -ly.
    if w.endswith("ly") and len(w) > 4:
        w = w[:-2]              # happily -> happi

    return w
