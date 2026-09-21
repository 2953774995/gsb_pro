from kbsearch import KBSearch


def test_add_and_tf_df():
    kb = KBSearch()
    kb.add_document(1, "compressor compressor noise")
    kb.add_document(2, "compressor leak")
    assert kb.document_count() == 2
    assert kb.index.postings["compressor"][1][0] == 2   # tf
    assert kb.index.postings["compressor"][2][0] == 1
    assert kb.index.df("compressor") == 2               # df
    assert kb.index.df("noise") == 1
    assert kb.index.doc_lengths[1] == 3                 # doc length
    assert kb.index.doc_lengths[2] == 2


def test_positions_recorded():
    kb = KBSearch()
    kb.add_document(1, "a b a")  # stopwords off? 'a' is a stopword
    kb2 = KBSearch(use_stopwords=False)
    kb2.add_document(1, "x y x")
    assert kb2.index.postings["x"][1][1] == [0, 2]
    assert kb2.index.postings["y"][1][1] == [1]


def test_repeated_add_overwrites():
    kb = KBSearch()
    kb.add_document(1, "apple apple apple")
    kb.add_document(1, "banana")
    assert kb.document_count() == 1
    assert "apple" not in kb.index.postings
    assert kb.index.postings["banana"][1][0] == 1
    assert kb.index.doc_lengths[1] == 1


def test_remove_cleans_postings():
    kb = KBSearch()
    kb.add_document(1, "apple banana")
    kb.add_document(2, "apple cherry")
    kb.remove_document(1)
    assert kb.document_count() == 1
    assert "banana" not in kb.index.postings            # term fully gone
    assert set(kb.index.postings["apple"].keys()) == {2}
    assert 1 not in kb.index.doc_lengths
    assert 1 not in kb.index.doc_texts
    kb.remove_document(2)
    assert kb.index.postings == {}
    assert kb.document_count() == 0


def test_remove_unknown_id_is_noop():
    kb = KBSearch()
    kb.add_document(1, "apple")
    kb.remove_document(999)
    assert kb.document_count() == 1


def test_int_and_str_doc_ids():
    kb = KBSearch()
    kb.add_document(1, "apple")
    kb.add_document("1", "banana")
    kb.add_document("doc-a", "apple")
    assert kb.document_count() == 3
    ids = {h["doc_id"] for h in kb.search("apple", top_k=0)}
    assert ids == {1, "doc-a"}
