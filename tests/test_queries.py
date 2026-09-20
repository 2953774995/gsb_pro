import pytest

from kbsearch import KBSearch, SearchError


def build():
    kb = KBSearch()
    kb.add_document("compressor", "压缩机 异响 冰箱 compressor noisy fan")
    kb.add_document("cooling", "冰箱 不制冷 freezer does not cool")
    kb.add_document("motor", "电机 风扇 损坏 motor fan broken")
    kb.add_document("manual", "维修手册 记录 压缩机 更换 repair manual compressor replace")
    return kb


def ids(results):
    return [r["doc_id"] for r in results]


def test_and_or_not_parentheses_semantics():
    kb = build()
    assert ids(kb.search("压缩机 AND (异响 OR 不制冷)", top_k=0)) == ["compressor"]
    or_result = kb.search("冰箱 OR 电机", top_k=0)
    assert set(ids(or_result)) == {"compressor", "cooling", "motor"}
    # 电机 is rarer and therefore ranks ahead of the two 冰箱 documents.
    assert ids(or_result)[0] == "motor"
    result = ids(kb.search("NOT 冰箱", top_k=0))
    assert result == ["manual", "motor"]
    assert ids(kb.search("压缩机 AND NOT 异响", top_k=0)) == ["manual"]


def test_implicit_and_keywords_case_insensitive():
    kb = build()
    assert ids(kb.search("压缩机 and 异响", top_k=0)) == ["compressor"]
    assert ids(kb.search("电机 OR 压缩机", top_k=0)) == [
        "compressor", "manual", "motor"
    ]


def test_phrase_query_by_positions():
    kb = build()
    assert ids(kb.search('"不制冷"', top_k=0)) == ["cooling"]
    assert ids(kb.search('"compressor noisy"', top_k=0)) == ["compressor"]
    # Same terms, different order must not be a phrase match.
    assert kb.search('"noisy compressor"', top_k=0) == []


def test_prefix_query_expands_dictionary():
    kb = build()
    assert ids(kb.search("comp*", top_k=0)) == ["compressor", "manual"]
    assert ids(kb.search("冰*", top_k=0)) == ["compressor", "cooling"]
    assert kb.search("zzz*", top_k=0) == []


def test_invalid_queries_raise_search_error_with_reason():
    kb = build()
    invalid = ["", "   ", "AND", "compressor AND", "OR fan", "NOT",
               "(compressor", "compressor)", "(())", "AND fan",
               '"unclosed phrase', "compressor *", "a OR", "NOT AND"]
    for query in invalid:
        with pytest.raises(SearchError):
            kb.search(query)


def test_empty_index_returns_empty_not_error_for_valid_not():
    kb = KBSearch()
    assert kb.search("压缩机", top_k=0) == []
    assert kb.search("NOT 压缩机", top_k=0) == []


def test_top_k_and_no_match():
    kb = build()
    assert len(kb.search("OR".replace("OR", "压缩机 OR 冰箱 OR 电机 OR 维修"), top_k=2)) == 2
    assert kb.search("完全不存在的词组", top_k=0) == []
    with pytest.raises(ValueError):
        kb.search("压缩机", top_k=-1)


def test_multi_character_chinese_prefix_and_stopword_phrase():
    kb = KBSearch()
    kb.add_document("a", "压缩机启动失败 freezer does not cool")
    kb.add_document("b", "压力异常 but cooling ok")
    assert ids(kb.search("压缩*", top_k=0)) == ["a"]
    assert ids(kb.search('"freezer does not cool"', top_k=0)) == ["a"]
    with pytest.raises(SearchError):
        kb.search("the")


def test_quoted_all_stopword_phrase_can_match_textually():
    kb = KBSearch()
    kb.add_document("a", "the is exact note")
    kb.add_document("b", "the separate is elsewhere")
    assert ids(kb.search('"the is"', top_k=0)) == ["a"]


def test_plain_chinese_punctuation_is_implicit_separator():
    kb = KBSearch()
    kb.add_document("a", "冰箱，压缩机异响。")
    assert ids(kb.search("冰箱，压缩机", top_k=0)) == ["a"]
    assert ids(kb.search("异响！", top_k=0)) == ["a"]
