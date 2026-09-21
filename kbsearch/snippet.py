"""Hit-summary (snippet) generation."""


def make_snippet(text, terms, tokenizer, window=80):
    """Return a snippet of about *window* chars around the first hit term.

    *terms* is a set of normalized (indexed) terms; the document text is
    re-tokenized with offsets so English stems and Chinese unigrams both
    line up with the original surface text.
    """
    if not text:
        return ""
    hit = None
    if terms:
        for tok, start, end in tokenizer.tokenize_with_spans(text):
            if tok in terms:
                hit = (start, end)
                break
    if hit is None:
        snippet = text[:window]
        return " ".join(snippet.split()) + ("..." if len(text) > window else "")
    start, end = hit
    half = window // 2
    s = max(0, start - half)
    e = min(len(text), end + half)
    snippet = " ".join(text[s:e].split())
    prefix = "..." if s > 0 else ""
    suffix = "..." if e < len(text) else ""
    return prefix + snippet + suffix
