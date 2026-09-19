"""Hit-summary (snippet) generation.

Picks the earliest occurrence of any query term in the raw document text
and returns a window of at most `width` characters around it, with
ellipsis marks when the window is truncated.
"""


def generate_snippet(text, raw_terms, width=80):
    if not text:
        return ""
    lowered = text.lower()
    best = None
    for term in raw_terms:
        if not term:
            continue
        position = lowered.find(term.lower())
        if position != -1 and (best is None or position < best):
            best = position
    if best is None:
        snippet = text[:width]
        return snippet + ("..." if len(text) > width else "")

    half = width // 2
    start = max(0, best - half)
    end = min(len(text), start + width)
    start = max(0, end - width)
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet.lstrip()
    if end < len(text):
        snippet = snippet.rstrip() + "..."
    return snippet
