from minisearch.tokenizer import Tokenizer, stem


def test_english_lowercase_and_split():
    tok = Tokenizer(use_stopwords=False)
    assert tok.tokenize("Hello, WORLD!") == ["hello", "world"]


def test_alphanumeric_tokens():
    tok = Tokenizer(use_stopwords=False)
    assert tok.tokenize("Python3.11 rocks!") == ["python3", "11", "rock"]


def test_mixed_chinese_english():
    tok = Tokenizer(use_stopwords=False)
    assert tok.tokenize("hello世界") == ["hello", "世", "界"]


def test_chinese_char_by_char():
    tok = Tokenizer(use_stopwords=False)
    assert tok.tokenize("全文搜索引擎") == ["全", "文", "搜", "索", "引", "擎"]


def test_punctuation_separates_cjk_and_latin():
    tok = Tokenizer(use_stopwords=False)
    assert tok.tokenize("搜索，engine。") == ["搜", "索", "engine"]


def test_stopwords_on_off():
    assert Tokenizer(use_stopwords=True).tokenize("the cat is a dog") == ["cat", "dog"]
    assert Tokenizer(use_stopwords=False).tokenize("the cat") == ["the", "cat"]


def test_custom_stopwords():
    tok = Tokenizer(use_stopwords=True, stopwords={"foo"})
    assert tok.tokenize("foo bar") == ["bar"]


def test_stemming_rules():
    assert stem("running") == "run"
    assert stem("studies") == "study"
    assert stem("cats") == "cat"
    assert stem("played") == "play"
    assert stem("this") == "this"   # ends with 'is', kept
    assert stem("class") == "class"  # ends with 'ss', kept
    assert stem("go") == "go"        # too short


def test_empty_and_punctuation_only():
    tok = Tokenizer()
    assert tok.tokenize("") == []
    assert tok.tokenize("!!! ??? ...") == []
