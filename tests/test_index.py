from minisearch.index import InvertedIndex
from minisearch.tokenizer import tokenize


def make_index():
    return InvertedIndex()


def add(index, doc_id, text):
    index.add_document(doc_id, tokenize(text))


def test_tf_and_positions():
    index = make_index()
    add(index, 1, "apple banana apple cherry apple")
    posting = index.get_posting("apple", 1)
    assert posting.tf == 3
    assert posting.positions == [0, 2, 4]
    assert index.get_posting("banana", 1).tf == 1


def test_document_frequency():
    index = make_index()
    add(index, 1, "apple banana")
    add(index, 2, "apple cherry")
    add(index, 3, "banana")
    assert index.document_frequency("apple") == 2
    assert index.document_frequency("banana") == 2
    assert index.document_frequency("cherry") == 1
    assert index.document_frequency("missing") == 0


def test_doc_length_counts_effective_tokens():
    index = make_index()
    add(index, 1, "the cat and the dog")  # stop words removed
    assert index.doc_length(1) == 2  # cat, dog


def test_readd_replaces_old_document():
    index = make_index()
    add(index, 1, "apple apple apple")
    add(index, 1, "banana")
    assert index.get_posting("apple", 1) is None
    assert index.document_frequency("apple") == 0
    assert index.get_posting("banana", 1).tf == 1
    assert index.document_count == 1
    assert index.doc_length(1) == 1


def test_remove_document_cleans_all_postings():
    index = make_index()
    add(index, 1, "apple banana")
    add(index, 2, "apple cherry")
    assert index.remove_document(1) is True
    assert index.document_frequency("apple") == 1
    assert index.document_frequency("banana") == 0
    assert "banana" not in index.vocabulary
    assert index.get_posting("apple", 1) is None
    assert index.get_posting("apple", 2).tf == 1
    assert index.doc_length(1) == 0
    assert index.document_count == 1


def test_remove_missing_document():
    index = make_index()
    assert index.remove_document("nope") is False


def test_remove_all_leaves_empty_index():
    index = make_index()
    add(index, 1, "apple banana")
    index.remove_document(1)
    assert index.document_count == 0
    assert list(index.vocabulary) == []
    assert index.doc_ids() == set()


def test_prefix_lookup():
    index = make_index()
    add(index, 1, "program programs programmer python")
    assert sorted(index.terms_with_prefix("program")) == [
        "program", "programmer"]
    assert index.terms_with_prefix("python") == ["python"]
    assert index.terms_with_prefix("zzz") == []


def test_int_and_str_doc_ids():
    index = make_index()
    add(index, 1, "apple")
    add(index, "one", "apple")
    assert index.document_frequency("apple") == 2
    assert index.doc_ids() == {1, "one"}
