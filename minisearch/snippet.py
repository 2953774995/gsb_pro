"""Hit-summary (snippet) generation.

A window of at most ``width`` characters centred on the first query-term
occurrence is extracted; ``...`` marks truncated sides.
"""

DEFAULT_WIDTH = 80
_ELLIPSIS = "..."


def make_snippet(text, terms, width=DEFAULT_WIDTH):
    """Return an excerpt of *text* around the first occurrence of any term
    in *terms* (case-insensitive).  Falls back to the head of the document
    when no term matches literally."""
    if not text:
        return ""
    lower = text.lower()
    hit = None
    for term in terms:
        term = term.lower()
        if not term:
            continue
        idx = lower.find(term)
        if idx != -1 and (hit is None or idx < hit[0]):
            hit = (idx, idx + len(term))
    if hit is None:
        end = min(len(text), width)
        return text[:end] + (_ELLIPSIS if end < len(text) else "")

    start, end = hit
    slack = max(0, width - (end - start))
    s = max(0, start - slack // 2)
    e = min(len(text), s + width)
    s = max(0, e - width)
    snippet = text[s:e]
    if s > 0:
        snippet = _ELLIPSIS + snippet
    if e < len(text):
        snippet = snippet + _ELLIPSIS
    return snippet
