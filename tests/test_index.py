"""Inverted index correctness: tf/df, overwrite on re-add, clean removal."""

from minisearch.index import InvertedIndex


def make_index():
    idx = InvertedIndex()
    idx.add_document(1, [("apple", 0), ("banana", 1), ("apple", 2)])
    idx.add_document(2, [("apple", 0)])
    return idx


def test_tf_via_positions_and_df():
    idx = make_index()
    assert idx.postings("apple")[1] == [0, 2]      # tf(apple, doc1) == 2
    assert idx.postings("apple")[2] == [0]
    assert idx.df("apple") == 2
    assert idx.df("banana") == 1
    assert idx.df("missing") == 0
    assert idx.postings("missing") == {}


def test_doc_length_and_document_count():
    idx = make_index()
    assert idx.doc_length(1) == 3
    assert idx.doc_length(2) == 1
    assert idx.document_count == 2


def test_readd_replaces_old_document():
    idx = make_index()
    idx.add_document(1, [("cherry", 0)])
    assert idx.df("apple") == 1                    # doc1's apple postings gone
    assert idx.df("banana") == 0
    assert "banana" not in idx.vocabulary()
    assert idx.postings("cherry")[1] == [0]
    assert idx.doc_length(1) == 1
    assert idx.document_count == 2                 # count unchanged


def test_remove_cleans_all_postings():
    idx = make_index()
    assert idx.remove_document(1) is True
    assert idx.df("apple") == 1
    assert idx.df("banana") == 0
    assert "banana" not in idx.vocabulary()
    assert idx.doc_length(1) == 0
    assert idx.document_count == 1
    # Removing again is a no-op.
    assert idx.remove_document(1) is False
    assert idx.document_count == 1


def test_remove_all_documents_leaves_empty_index():
    idx = make_index()
    idx.remove_document(1)
    idx.remove_document(2)
    assert idx.document_count == 0
    assert idx.vocabulary() == set()
    assert idx.doc_ids() == []


def test_int_and_str_doc_ids_coexist():
    idx = InvertedIndex()
    idx.add_document(1, [("x", 0)])
    idx.add_document("1", [("x", 0)])
    assert idx.df("x") == 2
    idx.remove_document(1)
    assert idx.df("x") == 1
    assert idx.doc_ids() == ["1"]


def test_prefix_scan():
    idx = make_index()
    assert idx.terms_with_prefix("app") == ["apple"]
    assert idx.terms_with_prefix("zzz") == []
