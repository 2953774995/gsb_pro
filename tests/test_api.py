"""Public API: compile/match/search/fullmatch/findall/finditer, Match."""

import regexlab


def test_compile_returns_reusable_pattern():
    p = regexlab.compile(r"\d+")
    assert p.match("123").group(0) == "123"
    assert p.match("456").group(0) == "456"
    assert p.pattern == r"\d+"
    assert p.groups == 0


def test_compile_caches_parsed_result():
    assert regexlab.compile("abc") is regexlab.compile("abc")


def test_compile_accepts_pattern_objects():
    p = regexlab.compile("abc")
    assert regexlab.compile(p) is p


def test_match_vs_search():
    assert regexlab.match("b", "abc") is None
    assert regexlab.search("b", "abc").span() == (1, 2)


def test_fullmatch():
    assert regexlab.fullmatch(r"\w+", "hello") is not None
    assert regexlab.fullmatch(r"\w+", "hello world") is None
    assert regexlab.match(r"\w+", "hello world") is not None  # partial ok


def test_findall_no_groups():
    assert regexlab.findall(r"\d+", "a1b22c333") == ["1", "22", "333"]


def test_findall_one_group_returns_group_contents():
    assert regexlab.findall(r"a(\d)", "a1a2a3") == ["1", "2", "3"]


def test_findall_multiple_groups_returns_tuples():
    assert regexlab.findall(r"(\w)=(\d)", "a=1 b=2") == [("a", "1"),
                                                         ("b", "2")]


def test_findall_non_overlapping():
    # "aa" can match at 0, 1, 2 in "aaaa"; non-overlapping means 2 hits.
    assert regexlab.findall("aa", "aaaa") == ["aa", "aa"]
    assert regexlab.findall("aa", "aaaaa") == ["aa", "aa"]


def test_finditer_yields_matches_with_positions():
    matches = list(regexlab.finditer(r"\d+", "a1b22c333"))
    assert [m.group(0) for m in matches] == ["1", "22", "333"]
    assert [m.span() for m in matches] == [(1, 2), (3, 5), (6, 9)]


def test_empty_pattern_matches_empty_string():
    m = regexlab.match("", "abc")
    assert m is not None
    assert m.group(0) == ""
    assert m.span() == (0, 0)


def test_empty_text():
    assert regexlab.match("", "") is not None
    assert regexlab.match("a", "") is None
    assert regexlab.fullmatch("a*", "") is not None
    assert regexlab.search("a*", "").group(0) == ""


def test_empty_matches_advance_in_findall():
    assert regexlab.findall("a*", "aab") == ["aa", "", ""]
    assert regexlab.findall("", "ab") == ["", "", ""]


def test_match_object_group_multiple_args():
    m = regexlab.match(r"(\w)(\d)", "a1")
    assert m.group(1, 2) == ("a", "1")
    assert m.group() == "a1"


def test_match_object_invalid_group():
    m = regexlab.match("(a)", "a")
    for bad in (2, -1, "x"):
        try:
            m.group(bad)
        except IndexError:
            pass
        else:
            raise AssertionError("expected IndexError for %r" % (bad,))


def test_match_object_repr():
    assert "Match" in repr(regexlab.match("a", "a"))


def test_purge_clears_cache():
    regexlab.compile("purge-test")
    regexlab.purge()
    assert regexlab.compile("purge-test") is not None
