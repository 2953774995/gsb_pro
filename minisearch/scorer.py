"""TF-IDF scoring.

    tf_weight = 1 + log(tf)          (log-normalised term frequency)
    idf       = log(1 + N / df)      (smoothed inverse document frequency)
    score     = tf_weight * idf      (summed over the matched terms)
"""

import math


def tf_idf(tf, df, n_docs):
    """Score of one term in one document."""
    if tf <= 0 or df <= 0 or n_docs <= 0:
        return 0.0
    return (1.0 + math.log(tf)) * math.log(1.0 + n_docs / df)
