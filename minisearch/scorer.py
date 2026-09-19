"""TF-IDF scoring helpers.

tf weight  = 1 + log(tf)          (logarithmic normalization)
idf        = log(1 + N / df)      (smoothed inverse document frequency)
"""

import math


class Scorer:
    def __init__(self, index):
        self.index = index

    def idf(self, df):
        n = self.index.document_count()
        if df <= 0 or n <= 0:
            return 0.0
        return math.log(1 + n / df)

    def term_scores(self, term):
        """Return {doc_id: tf-idf score} for one term."""
        postings = self.index.postings.get(term)
        if not postings:
            return {}
        idf = self.idf(len(postings))
        return {
            doc_id: (1 + math.log(len(positions))) * idf
            for doc_id, positions in postings.items()
        }
