from kbsearch.tokenizer import Analyzer
from kbsearch.stemmer import stem


def terms(text, use_stopwords=True):
    return [token.term for token in Analyzer(use_stopwords).analyze(text)]


def test_english_lowercase_stemming_and_numbers():
    assert terms("Repairs repaired fixing fixed boxes") == [
        "repair", "repair", "fix", "fix", "box"
    ]
    assert terms("Error E123 code 42") == ["error", "e123", "code", "42"]


def test_stopwords_configurable():
    text = "The fan is a motor of fridge"
    assert "the" not in terms(text, True)
    assert "the" in terms(text, False)
    assert "of" in terms(text, False)


def test_chinese_indexed_by_character_and_mixed_text():
    tokens = Analyzer().analyze("冰箱compressor异响 E10!")
    assert [t.term for t in tokens] == ["冰", "箱", "compressor", "异", "响", "e10"]
    assert [t.position for t in tokens] == [0, 1, 2, 3, 4, 5]
    assert tokens[0].start == 0 and tokens[0].end == 1


def test_punctuation_and_whitespace_are_separators():
    assert terms("hello,world; 你好。测试！") == [
        "hello", "world", "你", "好", "测", "试"
    ]


def test_stemmer_common_suffix_rules():
    assert stem("repairing") == "repair"
    assert stem("repairs") == "repair"
    assert stem("happily") == "happy"
    assert stem("motors") == "motor"
    assert stem("123") == "123"
