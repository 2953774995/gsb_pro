from minisearch.index import InvertedIndex
from minisearch.tokenizer import Tokenizer


def make_index(use_stopwords=True):
    return InvertedIndex(), Tokenizer(use_stopwords=use_stopwords)


def add(index, tok, doc_id, text):
    index.add_document(doc_id, tok.tokenize(text), text)


def test_add_and_term_stats():
    index, tok = make_index()
    add(index, tok, 1, "apple apple banana")
    assert index.document_count() == 1
    assert index.postings["apple"][1] == [0, 1]          # positions -> tf = 2
    assert index.postings["banana"][1] == [2]
    assert index.document_frequency("apple") == 1
    assert index.doc_lengths[1] == 3


def test_df_across_documents():
    index, tok = make_index()
    add(index, tok, 1, "apple banana")
    add(index, tok, 2, "apple cherry")
    add(index, tok, 3, "cherry")
    assert index.document_frequency("apple") == 2
    assert index.document_frequency("cherry") == 2
    assert index.document_frequency("banana") == 1


def test_readd_same_id_replaces():
    index, tok = make_index()
    add(index, tok, 1, "apple apple")
    add(index, tok, 1, "banana")
    assert index.document_count() == 1
    assert "apple" not in index.postings
    assert index.postings["banana"][1] == [0]
    assert index.doc_lengths[1] == 1


def test_remove_cleans_everything():
    index, tok = make_index()
    add(index, tok, 1, "apple banana")
    add(index, tok, 2, "apple cherry")
    assert index.remove_document(1) is True
    assert index.document_count() == 1
    assert "banana" not in index.postings            # term fully gone
    assert 1 not in index.postings["apple"]          # posting gone
    assert 1 not in index.doc_lengths
    assert 1 not in index.documents
    assert index.remove_document(1) is False         # already gone
    assert index.remove_document(999) is False       # never existed


def test_int_and_str_doc_ids():
    index, tok = make_index()
    add(index, tok, 1, "apple")
    add(index, tok, "one", "apple")
    assert index.document_count() == 2
    assert set(index.postings["apple"]) == {1, "one"}
