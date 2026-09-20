import math

from kbsearch import KBSearch


def test_chinese_and_english_synonyms_hit_without_double_counting():
    kb = KBSearch()
    kb.add_document(1, "冰柜 不制冷 freezer cool")
    kb.add_document(2, "冰箱 正常 fridge ok")
    kb.add_document(3, "需要 repair 压缩机")
    kb.add_synonym_group(["冰箱", "冰柜", "冷藏柜"])
    kb.add_synonym_group(["repair", "修理", "维修"])
    kb.add_synonym_group(["cooler", "chiller"])

    assert {r["doc_id"] for r in kb.search("冰箱", top_k=0)} == {1, 2}
    assert {r["doc_id"] for r in kb.search("维修", top_k=0)} == {3}

    # Expansion itself is one concept and must not internally sum variants.
    # Validate that by matching a document whose expanded term occurs twice;
    # its score remains a single idf rather than doubling.
    kb.add_document(4, "cooler chiller generic")
    expanded = {r["doc_id"]: r["score"]
                for r in kb.search("cooler", top_k=0) if r["doc_id"] == 4}
    assert expanded[4] == round(math.log(1 + 4 / 1), 8)


def test_load_synonym_file(tmp_path):
    path = tmp_path / "syn.txt"
    path.write_text("冰箱=冰柜=冷藏柜\n# comment\n维修=修理\n", encoding="utf-8")
    kb = KBSearch()
    kb.load_synonyms(str(path))
    kb.add_document("a", "冷藏柜温度异常")
    assert kb.search("冰箱", top_k=0)[0]["doc_id"] == "a"
