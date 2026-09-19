import pytest

from minisearch import SearchEngine


@pytest.fixture
def engine():
    eng = SearchEngine()
    eng.add_document(1, "the quick brown fox jumps over the lazy dog")
    eng.add_document(2, "quick brown foxes are quick and brown")
    eng.add_document(3, "brown quick fox")          # wrong word order
    eng.add_document(4, "nothing relevant here")
    return eng


def ids(results):
    return {hit["doc_id"] for hit in results}


def test_phrase_matches_adjacent_only(engine):
    assert ids(engine.search('"quick brown"')) == {1, 2}
    # doc 3 has the words in the wrong order; doc 2 matches via stemming
    assert ids(engine.search('"quick brown fox"')) == {1, 2}


def test_phrase_respects_positions(engine):
    assert ids(engine.search('"brown quick"')) == {3}
    assert ids(engine.search('"lazy dog"')) == {1}
    assert ids(engine.search('"dog lazy"')) == set()


def test_phrase_with_stemming(engine):
    # "foxes" stems to "fox", so the phrase matches doc 2 as well
    assert ids(engine.search('"brown fox"')) == {1, 2}


def test_phrase_in_boolean(engine):
    assert ids(engine.search('"quick brown" AND fox')) == {1, 2}
    assert ids(engine.search('"quick brown" AND NOT jump')) == {2}


def test_prefix_query(engine):
    assert ids(engine.search("qui*")) == {1, 2, 3}
    assert ids(engine.search("fox*")) == {1, 2, 3}
    assert ids(engine.search("laz*")) == {1}
    assert ids(engine.search("zzz*")) == set()


def test_prefix_case_insensitive(engine):
    assert ids(engine.search("QUI*")) == {1, 2, 3}


def test_prefix_combined_with_boolean(engine):
    assert ids(engine.search("qui* AND NOT brown")) == set()
    assert ids(engine.search("laz* OR zzz*")) == {1}


def test_chinese_phrase():
    eng = SearchEngine()
    eng.add_document(1, "全文搜索引擎实现")
    eng.add_document(2, "索引全文排序")
    assert ids(eng.search('"全文搜索"')) == {1}
    assert ids(eng.search('"搜索"')) == {1}
    assert ids(eng.search('"索引全文"')) == {2}
