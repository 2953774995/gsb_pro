"""A small deterministic English stemmer.

The implementation intentionally uses only conservative suffix rules instead
of a full Porter stemmer.  It is sufficient for common repair-manual vocabulary
(nouns, verbs and common derivational suffixes) while remaining easy to audit.
The same rules are applied to both indexed text and queries.
"""


def _ends_with_double_consonant(word: str) -> bool:
    return len(word) >= 2 and word[-1] == word[-2] and word[-1].isalpha()


def stem(word: str) -> str:
    """Return a simplified stem for a lower-case ASCII English token.

    Numbers and tokens shorter than three characters are returned unchanged.
    Examples: repairs -> repair, repairing -> repair, happily -> happi.
    """
    w = word.lower()
    if not w or not w.isascii() or (not w.isalpha()):
        return w
    if len(w) <= 3:
        return w

    # Plural / third-person singular endings.  Do these before -ed/-ing so
    # that forms such as "fixes" do not lose too much of the root.
    if w.endswith("sses"):
        return w[:-2]
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("ches") or w.endswith("shes") or w.endswith("xes"):
        return w[:-2]
    if w.endswith("ses") or w.endswith("zes"):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss") and not w.endswith("us"):
        return w[:-1]

    # Gerunds and past tense forms.
    if w.endswith("ying"):
        return w[:-4] + "y"
    if w.endswith("ied"):
        return w[:-3] + "y"
    if w.endswith("ing"):
        stemmed = w[:-3]
        if len(stemmed) >= 3 and _ends_with_double_consonant(stemmed):
            # running/running -> run; fixing does not enter this branch.
            stemmed = stemmed[:-1]
        return stemmed
    if w.endswith("ed"):
        stemmed = w[:-2]
        if len(stemmed) >= 3 and _ends_with_double_consonant(stemmed):
            stemmed = stemmed[:-1]
        # Common doubled/terminal-e patterns: agreed, hoped, caused.
        if stemmed.endswith("e") and (
            stemmed.endswith(("ee", "ag", "caus", "hop", "lik", "lov", "us"))
        ):
            return stemmed
        # A small closed set of cases where a final consonant represented the
        # root before -ed: repaired, opened, cleaned.
        if stemmed in {"repair", "open", "clean", "turn", "return", "call",
                       "install", "check", "cool", "fail", "fill", "pull",
                       "wait", "warn", "warm", "start", "stop", "load"}:
            return stemmed
        if stemmed.endswith("e"):
            return stemmed
        return stemmed

    # Adverb and common adjective/noun derivational endings.
    if w.endswith("ly") and len(w) > 4:
        stemmed = w[:-2]
        if stemmed.endswith("i"):
            return stemmed[:-1] + "y"
        if _ends_with_double_consonant(stemmed):
            return stemmed[:-1]
        return stemmed
    if w.endswith("ness") and len(w) > 6:
        return w[:-4]
    if w.endswith("ment") and len(w) > 6:
        return w[:-4]
    if w.endswith("tion") and len(w) > 6:
        return w[:-3]
    if w.endswith("able") and len(w) > 6:
        return w[:-4]
    if w.endswith("ible") and len(w) > 6:
        return w[:-4]
    if w.endswith("ful") and len(w) > 5:
        return w[:-3]
    return w
