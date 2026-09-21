from kbsearch import KBSearch


def test_snippet_contains_hit():
    kb = KBSearch()
    kb.add_document(1, "前言。" * 30 + "压缩机异响处理方案" + "后记。" * 30)
    hits = kb.search("压缩机", with_snippet=True)
    assert "snippet" in hits[0]
    assert "压缩机" in hits[0]["snippet"]


def test_snippet_length_bounded():
    kb = KBSearch()
    kb.add_document(1, "噪音 " * 200 + "目标词 " + "填充 " * 200)
    hits = kb.search("目标词", with_snippet=True)
    snippet = hits[0]["snippet"]
    assert "目标词" in snippet
    assert len(snippet) <= 80 + 6  # window + two ellipses


def test_snippet_english_hit():
    kb = KBSearch()
    kb.add_document(1, "word " * 50 + "compressor " + "word " * 50)
    hits = kb.search("compressor", with_snippet=True)
    assert "compressor" in hits[0]["snippet"]


def test_snippet_omitted_by_default():
    kb = KBSearch()
    kb.add_document(1, "压缩机")
    hits = kb.search("压缩机")
    assert "snippet" not in hits[0]


def test_snippet_no_hit_term_falls_back_to_head():
    kb = KBSearch()
    kb.add_document(1, "开头内容 " + "中间 " * 100)
    kb.add_document(2, "其他文档")
    # NOT query: no positive terms, snippet falls back to the text head
    hits = kb.search("NOT 不存在词", with_snippet=True)
    assert hits[0]["snippet"].startswith("开头内容") or hits[1]["snippet"].startswith("开头内容")
