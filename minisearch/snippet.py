"""Hit summaries: an ~80 character window around the first query-term hit."""


def make_snippet(text, terms, width=80):
    """Return a snippet of at most ``width`` chars of ``text`` around the
    earliest occurrence of any query term (plus ellipsis markers)."""
    if len(text) <= width:
        return text
    lower = text.lower()
    best = None
    for term in terms:
        if not term:
            continue
        idx = lower.find(term.lower())
        if idx != -1 and (best is None or idx < best):
            best = idx
    if best is None:
        return text[:width] + "..."
    half = width // 2
    start = max(0, best - half)
    end = min(len(text), start + width)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return prefix + text[start:end] + suffix
