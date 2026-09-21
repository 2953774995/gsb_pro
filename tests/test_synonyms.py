import math

import pytest

from kbsearch import KBSearch, SynonymMap


@pytest.fixture()
def syn_file(tmp_path):
    p = tmp_path / "synonyms.txt"
    p.write_text(
        "# comment line\n"
        "\n"
        "冰箱=冰柜=冷藏柜\n"
        "维修=修理\n"
        "fridge=refrigerator\n",
        encoding="utf-8",
    )
    return str(p)


def test_chinese_synonym_expansion(syn_file):
    kb = KBSearch(synonyms=SynonymMap.from_file(syn_file))
    kb.add_document(1, "这台冰柜制冷效果差")
    kb.add_document(2, "冷藏柜温度异常")
    kb.add_document(3, "洗衣机漏水")
    hits = {h["doc_id"] for h in kb.search("冰箱")}
    assert hits == {1, 2}


def test_english_synonym_expansion(syn_file):
    kb = KBSearch(synonyms=SynonymMap.from_file(syn_file))
    kb.add_document(1, "The refrigerator is loud")
    kb.add_document(2, "unrelated content")
    assert {h["doc_id"] for h in kb.search("fridge")} == {1}


def test_synonym_both_directions(syn_file):
    kb = KBSearch(synonyms=SynonymMap.from_file(syn_file))
    kb.add_document(1, "需要上门维修压缩机")
    kb.add_document(2, "安排修理风扇")
    assert {h["doc_id"] for h in kb.search("维修")} == {1, 2}
    assert {h["doc_id"] for h in kb.search("修理")} == {1, 2}


def test_no_double_counting(syn_file):
    # doc containing BOTH synonyms must not be scored twice per variant;
    # its score equals a doc with the same total occurrence count.
    syn = SynonymMap.from_file(syn_file)
    kb = KBSearch(synonyms=syn)
    kb.add_document("both", "冰箱 冰柜")          # one occurrence of each variant
    kb.add_document("twice", "冰箱 冰箱")          # two occurrences of one variant
    kb.add_document("once", "冰箱")
    res = {h["doc_id"]: h["score"] for h in kb.search("冰箱", top_k=0)}
    assert res["both"] == pytest.approx(res["twice"])
    assert res["both"] > res["once"]
    # exact hand-check: group tf=2, df=3 (union), N=3
    expected = (1 + math.log(2)) * math.log(1 + 3 / 3)
    assert res["both"] == pytest.approx(expected)


def test_score_matches_unexpanded_when_no_synonym_present(syn_file):
    syn = SynonymMap.from_file(syn_file)
    kb_syn = KBSearch(synonyms=syn)
    kb_plain = KBSearch()
    for kb in (kb_syn, kb_plain):
        kb.add_document(1, "冰箱 制冷 正常")
        kb.add_document(2, "其他 内容 填充")
    assert kb_syn.search("冰箱")[0]["score"] == pytest.approx(
        kb_plain.search("冰箱")[0]["score"]
    )


def test_without_synonyms_no_expansion(syn_file):
    kb = KBSearch()  # no synonym table
    kb.add_document(1, "这台冰柜制冷效果差")
    assert kb.search("冰箱") == []


def test_comma_separated_groups(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("扳手,起子，螺丝刀\n", encoding="utf-8")
    syn = SynonymMap.from_file(str(p))
    assert set(syn.expand("扳手")) == {"扳手", "起子", "螺丝刀"}
