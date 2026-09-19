"""Tokenization: mixed Chinese/English, case, punctuation, stemming, stopwords."""

from minisearch.stemmer import stem
from minisearch.stopwords import DEFAULT_STOPWORDS
from minisearch.tokenizer import terms, tokenize


def test_english_lowercased_and_split_on_punctuation():
    assert terms("Hello, World!") == ["hello", "world"]


def test_alphanumeric_tokens_kept_together():
    assert terms("Python3 360 v2") == ["python3", "360", "v2"]


def test_punctuation_and_symbols_are_separators():
    assert terms("foo-bar_baz@qux#quux") == ["foo", "bar", "baz", "qux", "quux"]


def test_chinese_indexed_char_by_char():
    assert terms("我爱北京") == ["我", "爱", "北", "京"]


def test_mixed_chinese_english():
    assert terms("Python编程语言") == ["python", "编", "程", "语", "言"]
    assert terms("全文search引擎") == ["全", "文", "search", "引", "擎"]


def test_stemming_rules():
    assert stem("running") == "run"
    assert stem("cats") == "cat"
    assert stem("studies") == "studi"
    assert stem("caresses") == "caress"
    assert stem("played") == "play"
    assert stem("happily") == "happi"
    assert terms("running cats") == ["run", "cat"]


def test_stopwords_removed():
    assert terms("the cat is on a mat", stopwords=DEFAULT_STOPWORDS) == ["cat", "mat"]


def test_stopwords_can_be_disabled():
    assert terms("the cat", stopwords=None) == ["the", "cat"]


def test_positions_track_original_token_stream():
    # "the" is a stopword but still consumes position 0.
    assert tokenize("the cat", stopwords=DEFAULT_STOPWORDS) == [("cat", 1)]
    assert tokenize("cat dog", stopwords=DEFAULT_STOPWORDS) == [("cat", 0), ("dog", 1)]


def test_empty_and_symbol_only_text():
    assert tokenize("") == []
    assert tokenize("!@#$%^&*()") == []
