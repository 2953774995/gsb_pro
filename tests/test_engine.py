"""匹配引擎语义测试：字面量、字符类、量词、分组、锚点、交替、标志位。"""

from datamask import IGNORECASE, MULTILINE, compile


def test_literal_match():
    p = compile("abc")
    assert p.search("xxabcxx").span() == (2, 5)
    assert p.search("abd") is None


def test_dot_does_not_match_newline():
    assert compile("a.b").search("a\nb") is None
    assert compile("a.b").search("axb").group() == "axb"
    # .* 不跨行
    assert compile(".*").search("ab\ncd").group() == "ab"


def test_star_allows_zero():
    p = compile("ab*c")
    assert p.search("ac").group() == "ac"
    assert p.search("abbc").group() == "abbc"


def test_plus_requires_one():
    p = compile("ab+c")
    assert p.search("ac") is None
    assert p.search("abc").group() == "abc"


def test_question_optional():
    p = compile("colou?r")
    assert p.search("color") is not None
    assert p.search("colour") is not None
    assert p.search("colouur") is None


def test_brace_quantifier_bounds():
    p = compile("a{2,4}")
    assert p.search("a") is None
    assert p.search("aa").group() == "aa"
    assert p.search("aaaa").group() == "aaaa"
    assert p.search("aaaaa").group() == "aaaa"  # 贪婪但受上限约束
    assert compile("a{3}").search("aaaa").group() == "aaa"
    assert compile("a{2,}").search("aaaaa").group() == "aaaaa"


def test_greedy_vs_lazy():
    text = "<a><b>"
    assert compile("<.+>").search(text).group() == text
    assert compile("<.+?>").search(text).group() == "<a>"
    assert compile("a+?").search("aaa").group() == "a"
    assert compile("a*?").search("aaa").group() == ""
    assert compile("a{1,3}?").search("aaa").group() == "a"


def test_leftmost_wins_over_length():
    # 最左优先：位置 0 的短命中胜过位置 2 的长命中
    m = compile("a+").search("aaXaaa")
    assert m.span() == (0, 2)


def test_charclass_basics():
    assert compile("[abc]+").search("xxabcbayy").group() == "abcba"
    assert compile("[^abc]+").search("abxyza").group() == "xyz"
    assert compile("[a-z0-9]+").search("--az09--").group() == "az09"


def test_charclass_negated_newline():
    # 取反字符类可以匹配换行（与常见引擎一致）
    assert compile("[^a]").search("\n") is not None


def test_class_codes():
    assert compile(r"\d+").search("ab123cd").group() == "123"
    assert compile(r"\D+").search("123ab cd456").group() == "ab cd"
    assert compile(r"\w+").search("  a_1中文  ").group() == "a_1中文"
    assert compile(r"\W+").search("ab  cd").group() == "  "
    assert compile(r"\s+").search("a \t\nb").group() == " \t\n"
    assert compile(r"\S+").search("  ab c").group() == "ab"


def test_escape_literals_in_match():
    assert compile(r"a\.b").search("a.b") is not None
    assert compile(r"a\.b").search("axb") is None
    assert compile(r"\(\*\)").search("(*)") is not None
    assert compile(r"a\nb").search("a\nb") is not None
    assert compile(r"\x41\x42").search("AB") is not None


def test_groups_and_nesting():
    m = compile("((a)(b))").search("xab")
    assert m.group(0) == "ab"
    assert m.group(1) == "ab"
    assert m.group(2) == "a"
    assert m.group(3) == "b"
    assert m.groups() == ("ab", "a", "b")
    assert m.span(2) == (1, 2)


def test_group_not_participating():
    m = compile("(a)|(b)").search("b")
    assert m.group(0) == "b"
    assert m.group(1) is None
    assert m.group(2) == "b"
    assert m.groups() == (None, "b")
    assert m.span(1) == (-1, -1)


def test_named_groups():
    p = compile(r"(?P<year>\d{4})-(?P<month>\d{2})")
    m = p.search("date 2026-09")
    assert m.group("year") == "2026"
    assert m.group("month") == "09"
    assert m.group(1) == "2026"  # 命名组仍可通过编号访问
    assert m.groupdict() == {"year": "2026", "month": "09"}
    assert p.groupindex == {"year": 1, "month": 2}


def test_non_capturing_group():
    p = compile("(?:ab)+c")
    assert p.groups == 0
    assert p.search("ababc").group() == "ababc"


def test_group_in_repeat_captures_last_iteration():
    m = compile("(a|b)+").search("abab")
    assert m.group(1) == "b"
    assert m.span(1) == (3, 4)


def test_alternation_left_to_right_preference():
    assert compile("a|ab").search("ab").group() == "a"
    assert compile("ab|a").search("ab").group() == "ab"
    # 交替回溯：左分支整体失败后才尝试右分支
    assert compile("(a|ab)(c|bcd)").search("abcd").group() == "abcd"


def test_alternation_backtracks_into_branches():
    # fullmatch 下 a|ab 必须能通过回溯选 ab 才能匹配完整串
    assert compile("a|ab").fullmatch("ab") is not None


def test_anchors_default():
    p = compile("^abc$")
    assert p.search("abc") is not None
    assert p.search("xabc") is None
    assert p.search("abcx") is None
    assert p.search("ab\nc") is None


def test_anchor_dollar_before_trailing_newline():
    # 非多行模式下 $ 也匹配串尾换行前的位置（与常见引擎一致）
    assert compile("abc$").search("abc\n") is not None
    assert compile("abc$").search("abc\ndef") is None


def test_multiline_anchors():
    text = "foo\nbar\nbaz"
    p = compile("^bar$", MULTILINE)
    assert p.search(text).span() == (4, 7)
    # $ 匹配换行前位置
    assert [m.span() for m in compile("o$", MULTILINE).finditer(text)] == [(2, 3)]
    # ^ 匹配每行行首
    assert len(compile("^", MULTILINE).findall(text)) == 3
    # 非多行模式不命中行首
    assert compile("^bar").search(text) is None


def test_ignorecase():
    p = compile("abc", IGNORECASE)
    assert p.search("XXAbCxx").span() == (2, 5)
    assert compile("[a-z]+", IGNORECASE).search("ABC").group() == "ABC"
    assert compile("[^a]", IGNORECASE).search("A") is None
    assert compile(r"straße", IGNORECASE) is not None  # 编译期不报错


def test_ignorecase_unicode_fold():
    assert compile("k", IGNORECASE).search("K") is not None


def test_empty_pattern_matches_empty():
    p = compile("")
    m = p.search("abc")
    assert m.span() == (0, 0)
    assert m.group() == ""
    assert p.fullmatch("") is not None
    assert p.fullmatch("a") is None


def test_empty_input():
    assert compile("a*").fullmatch("").group() == ""
    assert compile("a+").search("") is None
    assert compile("").findall("") == [""]


def test_empty_loop_terminates():
    # 空体循环不得死循环
    assert compile("()*").search("abc") is not None
    assert compile("(a*)*").search("b") is not None
    assert compile("(?:|a)*").search("aa") is not None


def test_findall_empty_match_advances():
    assert compile("a*").findall("baa") == ["", "aa", ""]
    assert compile("").findall("ab") == ["", "", ""]


def test_pos_and_endpos():
    p = compile("b")
    assert p.search("abc", pos=2) is None
    assert p.search("abc", pos=1).span() == (1, 2)
    assert p.search("abc", endpos=1) is None
