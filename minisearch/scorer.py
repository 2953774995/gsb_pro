"""TF-IDF scoring and AST evaluation against the inverted index.

Scoring formula (per term, per document):
    tf_weight  = 1 + log(tf)              # logarithmic tf normalization
    idf        = log(1 + N / df)          # smoothed idf
    score      = tf_weight * idf

Boolean combination: AND intersects, OR unions, NOT subtracts; scores of
combined operands are summed. A bare NOT (or the NOT side of an AND)
contributes no score.
"""

import math

from .query import And, Not, Or, Phrase, Prefix, Term


def _tfidf(tf, df, num_docs):
    return (1.0 + math.log(tf)) * math.log(1.0 + num_docs / df)


def evaluate(node, index):
    """Evaluate an AST against the index. Returns {doc_id: score}."""
    num_docs = index.document_count
    if num_docs == 0:
        return {}

    if isinstance(node, Term):
        result = {}
        df = index.document_frequency(node.term)
        if df == 0:
            return result
        for doc_id, posting in index.get_postings(node.term).items():
            result[doc_id] = _tfidf(posting.tf, df, num_docs)
        return result

    if isinstance(node, Prefix):
        result = {}
        for term in index.terms_with_prefix(node.prefix):
            df = index.document_frequency(term)
            for doc_id, posting in index.get_postings(term).items():
                result[doc_id] = result.get(doc_id, 0.0) + _tfidf(
                    posting.tf, df, num_docs)
        return result

    if isinstance(node, Phrase):
        return _evaluate_phrase(node.terms, index, num_docs)

    if isinstance(node, And):
        combined = None
        for child in node.children:
            if isinstance(child, Not):
                excluded = set(evaluate(child.child, index))
                if combined is None:
                    combined = {doc_id: 0.0
                                for doc_id in index.doc_ids() - excluded}
                else:
                    for doc_id in list(combined):
                        if doc_id in excluded:
                            del combined[doc_id]
                continue
            scores = evaluate(child, index)
            if combined is None:
                combined = dict(scores)
            else:
                for doc_id in list(combined):
                    if doc_id in scores:
                        combined[doc_id] += scores[doc_id]
                    else:
                        del combined[doc_id]
        return combined if combined is not None else {}

    if isinstance(node, Or):
        combined = {}
        for child in node.children:
            if isinstance(child, Not):
                excluded = set(evaluate(child.child, index))
                for doc_id in index.doc_ids() - excluded:
                    combined.setdefault(doc_id, 0.0)
                continue
            scores = evaluate(child, index)
            for doc_id, score in scores.items():
                combined[doc_id] = combined.get(doc_id, 0.0) + score
        return combined

    if isinstance(node, Not):
        excluded = set(evaluate(node.child, index))
        return {doc_id: 0.0 for doc_id in index.doc_ids() - excluded}

    raise TypeError("unknown AST node: %r" % (node,))


def _evaluate_phrase(terms, index, num_docs):
    postings_per_term = [index.get_postings(term) for term in terms]
    if any(not postings for postings in postings_per_term):
        return {}
    candidate_docs = set(postings_per_term[0])
    for postings in postings_per_term[1:]:
        candidate_docs &= set(postings)
    result = {}
    for doc_id in candidate_docs:
        position_sets = [set(postings[doc_id].positions)
                         for postings in postings_per_term]
        occurrences = 0
        for start in postings_per_term[0][doc_id].positions:
            if all(start + offset in position_sets[offset]
                   for offset in range(1, len(terms))):
                occurrences += 1
        if occurrences:
            result[doc_id] = occurrences  # temporary: phrase tf
    df = len(result)
    for doc_id, phrase_tf in result.items():
        result[doc_id] = _tfidf(phrase_tf, df, num_docs)
    return result
