import pytest

from kbsearch import KBSearch, SearchError


@pytest.fixture()
def kb():
    kb = KBSearch()
    kb.add_document(1, "压缩机 异响 维修手册")
    kb.add_document(2, "压缩机 不制冷 冷媒泄漏")
    kb.add_document(3, "空调 异响 风扇")
    kb.add_document(4, "冰箱 冷藏柜 温度")
    return kb


def ids(results):
    return {h["doc_id"] for h in results}


def test_and(kb):
    assert ids(kb.search("压缩机 AND 异响")) == {1}


def test_or(kb):
    assert ids(kb.search("异响 OR 冷媒")) == {1, 2, 3}


def test_not_unary(kb):
    assert ids(kb.search("NOT 压缩机")) == {3, 4}


def test_and_not(kb):
    assert ids(kb.search("压缩机 AND NOT 异响")) == {2}


def test_parentheses_grouping(kb):
    assert ids(kb.search("压缩机 AND (异响 OR 不制冷)")) == {1, 2}


def test_precedence_and_binds_tighter(kb):
    # a OR b AND c  ==  a OR (b AND c)
    assert ids(kb.search("风扇 OR 压缩机 AND 异响")) == {1, 3}


def test_implicit_and(kb):
    assert ids(kb.search("压缩机 异响")) == {1}


def test_chinese_term_matches(kb):
    assert ids(kb.search("压缩机")) == {1, 2}
    assert ids(kb.search("冷藏柜")) == {4}


def test_phrase_query():
    kb = KBSearch()
    kb.add_document(1, "the quick brown fox jumps")
    kb.add_document(2, "the brown quick fox")
    kb.add_document(3, "空调不制冷维修")
    kb.add_document(4, "空调不制热制冷交替")
    assert ids(kb.search('"quick brown"')) == {1}
    assert ids(kb.search('"brown quick"')) == {2}
    assert ids(kb.search('"不制冷"')) == {3}
    # bare multi-char Chinese word behaves like a phrase
    assert ids(kb.search("不制冷")) == {3}


def test_prefix_query():
    kb = KBSearch()
    kb.add_document(1, "compressor compression compress")
    kb.add_document(2, "computer repair")
    kb.add_document(3, "nothing relevant")
    assert ids(kb.search("comp*")) == {1, 2}
    assert ids(kb.search("compress*")) == {1}
    assert ids(kb.search("zzz*")) == set()


def test_prefix_matches_stemmed_vocabulary():
    kb = KBSearch()
    kb.add_document(1, "repairs repairing repaired")
    assert ids(kb.search("repair*")) == {1}


def test_empty_index_returns_empty_list():
    kb = KBSearch()
    assert kb.search("anything") == []
    assert kb.search("anything AND everything") == []


def test_no_match_returns_empty_list(kb):
    assert kb.search("不存在的词xyz") == []


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "AND",
        "OR",
        "NOT",
        "AND 压缩机",
        "压缩机 AND",
        "压缩机 OR",
        "()",
        "(压缩机",
        "压缩机)",
        "(压缩机 AND)",
        '"未闭合短语',
        "*",
        "the",          # stop-word only -> no searchable tokens
    ],
)
def test_illegal_queries_raise_search_error(kb, bad):
    with pytest.raises(SearchError):
        kb.search(bad)


def test_error_has_reason(kb):
    with pytest.raises(SearchError) as excinfo:
        kb.search("压缩机 AND")
    assert str(excinfo.value)


def test_case_insensitive_query(kb):
    kb.add_document(9, "Compressor Noise")
    assert ids(kb.search("COMPRESSOR")) >= {9}
    assert ids(kb.search("compressor noise")) >= {9}  # implicit AND
