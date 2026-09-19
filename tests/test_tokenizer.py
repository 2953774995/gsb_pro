from minisearch.tokenizer import DEFAULT_STOP_WORDS, simple_stem, tokenize


def terms(text, **kwargs):
    return [term for term, _ in tokenize(text, **kwargs)]


def test_english_lowercase_and_split():
    assert terms("Hello World") == ["hello", "world"]


def test_case_insensitive():
    assert terms("PyThOn") == ["python"]


def test_punctuation_separates_words():
    assert terms("hello, world! foo-bar; baz.qux") == [
        "hello", "world", "foo", "bar", "baz", "qux"]


def test_alphanumeric_tokens():
    assert terms("python3 utf8 404") == ["python3", "utf8", "404"]


def test_chinese_char_unigrams():
    assert terms("搜索引擎") == ["搜", "索", "引", "擎"]


def test_mixed_chinese_english():
    assert terms("我爱Python编程") == ["我", "爱", "python", "编", "程"]


def test_positions_are_sequential():
    pairs = tokenize("one two three")
    assert [pos for _, pos in pairs] == [0, 1, 2]


def test_stop_words_removed_by_default():
    assert terms("this is a test of the engine") == ["test", "engine"]


def test_stop_words_can_be_disabled():
    result = terms("this is a test", use_stop_words=False)
    assert "is" in result and "a" in result and "this" in result


def test_custom_stop_words():
    result = terms("alpha beta gamma", stop_words=frozenset({"beta"}))
    assert result == ["alpha", "gamma"]


def test_stemming_rules():
    assert simple_stem("running") == "run"
    assert simple_stem("walked") == "walk"
    assert simple_stem("cats") == "cat"
    assert simple_stem("cities") == "city"
    assert simple_stem("boxes") == "box"
    assert simple_stem("searching") == "search"


def test_stemming_can_be_disabled():
    assert terms("running", stem=False) == ["running"]


def test_default_stop_words_cover_common_words():
    for word in ("a", "the", "is", "of", "and", "or", "not", "in", "to"):
        assert word in DEFAULT_STOP_WORDS
