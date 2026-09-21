from kbsearch.tokenizer import Tokenizer, stem


def test_mixed_chinese_english():
    toks = Tokenizer().tokenize("Compressor压缩机Noise")
    assert toks == ["compressor", "压", "缩", "机", "noise"]


def test_case_insensitive():
    assert Tokenizer().tokenize("ABC abc AbC") == ["abc", "abc", "abc"]


def test_punctuation_splits_tokens():
    toks = Tokenizer().tokenize("repair,manual.v2; (test) [ok]")
    assert toks == ["repair", "manual", "v2", "test", "ok"]


def test_stemming_rules():
    assert stem("repairs") == "repair"
    assert stem("repaired") == "repair"
    assert stem("repairing") == "repair"
    assert stem("noises") == "noise"
    assert stem("quickly") == "quick"
    assert stem("class") == "class"  # 'ss' is not stripped
    assert stem("is") == "is"        # too short to strip


def test_inflected_forms_match():
    kb_tok = Tokenizer()
    assert kb_tok.tokenize("repairs") == kb_tok.tokenize("repairing")


def test_stopwords_on_off():
    assert Tokenizer(use_stopwords=True).tokenize("the is of a compressor") == ["compressor"]
    assert Tokenizer(use_stopwords=False).tokenize("the is of") == ["the", "is", "of"]


def test_chinese_unigrams():
    assert Tokenizer().tokenize("不制冷") == ["不", "制", "冷"]


def test_spans_offsets():
    spans = Tokenizer().tokenize_with_spans("ab 制冷 cd")
    assert spans[0] == ("ab", 0, 2)
    assert spans[1] == ("制", 3, 4)
    assert spans[2] == ("冷", 4, 5)
    assert spans[3] == ("cd", 6, 8)
