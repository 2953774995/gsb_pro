"""分词边界：中英文混合、大小写、标点、停止词、词干化。"""

from minisearch.tokenizer import DEFAULT_STOPWORDS, stem, tokenize


def terms(text, **kw):
    return [t for t, _ in tokenize(text, **kw)]


def test_english_lowercase_and_split():
    assert terms("Hello, World!") == ["hello", "world"]


def test_case_insensitive():
    assert terms("Python PYTHON PyThOn") == ["python", "python", "python"]


def test_mixed_chinese_english():
    assert terms("我爱Python编程") == ["我", "爱", "python", "编", "程"]


def test_chinese_char_units():
    assert terms("北京天安门") == ["北", "京", "天", "安", "门"]


def test_punctuation_separates_tokens():
    # of/the 为停止词被过滤，但位置编号保留
    toks = tokenize("state-of-the-art!")
    assert [t for t, _ in toks] == ["state", "art"]
    assert [p for _, p in toks] == [0, 3]


def test_alphanumeric_tokens():
    assert terms("python3 3.14 utf8") == ["python3", "3", "14", "utf8"]


def test_stopwords_filtered_by_default():
    assert "the" in DEFAULT_STOPWORDS
    assert terms("the quick fox") == ["quick", "fox"]


def test_stopwords_can_be_disabled():
    assert terms("the quick fox", use_stopwords=False) == ["the", "quick", "fox"]


def test_stemming_rules():
    assert stem("cats") == "cat"
    assert stem("caresses") == "caress"
    assert stem("ponies") == "poni"
    assert stem("running") == "run"
    assert stem("stopped") == "stop"
    assert stem("played") == "play"
    assert stem("class") == "class"


def test_stemming_applied_in_tokenize():
    assert terms("running cats") == ["run", "cat"]


def test_stemming_can_be_disabled():
    assert terms("running", use_stemming=False) == ["running"]


def test_empty_and_symbol_only_text():
    assert terms("") == []
    assert terms("！？。，、") == []
