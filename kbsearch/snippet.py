"""Hit-snippet generation."""
from __future__ import annotations

from typing import List

from .index import InvertedIndex
from .query import RuntimeNode
from .tokenizer import Token


def _positive_terms(node: RuntimeNode) -> List[str]:
    """Collect scored terms, skipping the operand of a NOT node."""
    if node.kind == "NOT":
        return []
    if node.kind in ("TERM", "PREFIX", "PHRASE"):
        terms = []
        if node.term:
            terms.append(node.term)
        if node.terms:
            terms.extend(node.terms)
        return terms
    result = []
    for child in node.children:
        result.extend(_positive_terms(child))
    return result


def collect_query_spans(index: InvertedIndex, query_node: RuntimeNode,
                        text: str) -> List[Token]:
    terms = set(_positive_terms(query_node))
    # Expand prefix nodes recursively, but do not descend into a NOT operand:
    # an excluded term is not a positive hit and should not drive the snippet.
    stack = [query_node]
    while stack:
        current = stack.pop()
        if current.kind == "NOT":
            continue
        if current.kind == "PREFIX":
            terms.update(index.terms_with_prefix(current.prefix))
        stack.extend(current.children)
    return [token for token in index.analyzer.tokenize_all(text)
            if token.term in terms]


def make_snippet(index: InvertedIndex, query_node: RuntimeNode, text: str,
                 max_chars: int = 80) -> str:
    """Return at most ``max_chars`` characters around the first hit.

    Ellipses are included in the 80-character budget.  Newline characters are
    replaced with spaces so CLI output stays on one line.
    """
    if not text:
        return ""

    hits = collect_query_spans(index, query_node, text)
    if not hits:
        normalized = text.replace("\n", " ").replace("\r", " ")
        if len(normalized) <= max_chars:
            return normalized
        return normalized[:max_chars - 3] + "..."

    hit = hits[0]
    center = (hit.start + hit.end) // 2
    start = max(0, center - max_chars // 2)
    end = min(len(text), start + max_chars)
    start = max(0, end - max_chars)
    before = "..." if start > 0 else ""
    after = "..." if end < len(text) else ""

    # Reserve space for the one/two ellipses and shrink the text window.
    budget = max_chars - len(before) - len(after)
    if end - start > budget:
        end = start + budget
        start = max(0, end - budget)
        end = start + budget
    raw = text[start:end].replace("\n", " ").replace("\r", " ")
    return before + raw + after
