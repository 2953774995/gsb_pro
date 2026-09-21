from kbsearch import KBSearch


def test_delete_then_query_no_residue():
    kb = KBSearch()
    kb.add_document(1, "压缩机 异响")
    kb.add_document(2, "风扇 噪音")
    kb.remove_document(1)
    assert kb.search("压缩机") == []
    assert kb.search("异响") == []
    assert kb.search("压缩机 OR 风扇") != []
    assert {h["doc_id"] for h in kb.search("风扇")} == {2}


def test_delete_all_then_empty_results():
    kb = KBSearch()
    kb.add_document(1, "压缩机")
    kb.remove_document(1)
    assert kb.document_count() == 0
    assert kb.search("压缩机") == []


def test_modify_and_readd_old_term_gone_new_term_hits():
    kb = KBSearch()
    kb.add_document("ticket-1", "故障原因：电容老化，更换电容")
    assert kb.search("电容")
    kb.add_document("ticket-1", "故障原因：主板烧毁，更换主板")
    assert kb.search("电容") == []
    assert {h["doc_id"] for h in kb.search("主板")} == {"ticket-1"}
    assert kb.document_count() == 1
