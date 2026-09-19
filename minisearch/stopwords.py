"""Built-in English stopword list.

The list is intentionally small and conservative.  It can be disabled or
replaced entirely through ``SearchEngine(use_stopwords=False)`` or
``SearchEngine(stopwords={...})``.
"""

DEFAULT_STOPWORDS = frozenset({
    # articles / determiners
    "a", "an", "the", "this", "that", "these", "those",
    # be / have / do auxiliaries
    "is", "are", "was", "were", "be", "been", "being",
    "am", "do", "does", "did", "have", "has", "had",
    # prepositions / conjunctions
    "of", "to", "in", "on", "at", "for", "with", "by", "as", "from",
    "and", "or", "not", "but", "if", "then", "so", "such", "than",
    # pronouns
    "i", "you", "he", "she", "we", "they", "them", "his", "her",
    "their", "our", "it", "its",
})
