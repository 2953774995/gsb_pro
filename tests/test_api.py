"""Pattern/Match API: search/match/fullmatch/findall/finditer, empties."""

import rex


def test_search_match_fullmatch():
    p = rex.compile(r"\d+")
    assert p.search("abc123def").span() == (3, 6)
    assert p.match("abc123") is None
    assert p.match("123abc").group() == "123"
    assert p.fullmatch("123") is not None
    assert p.fullmatch("1234a") is None


def test_findall_no_groups():
    assert rex.compile(r"\d+").findall("a1b22c333") == ["1", "22", "333"]
    assert rex.compile("z").findall("abc") == []


def test_findall_one_group():
    assert rex.compile(r"(\d)+").findall("a12b3") == ["2", "3"]
    assert rex.compile(r"(\d+)").findall("a12b3") == ["12", "3"]


def test_findall_multiple_groups_returns_tuples():
    assert rex.compile(r"(\w+)=(\d+)").findall("a=1 b=22") == [
        ("a", "1"), ("b", "22"),
    ]


def test_finditer_yields_match_objects():
    matches = list(rex.compile(r"\d+").finditer("a1b22"))
    assert [m.group() for m in matches] == ["1", "22"]
    assert [m.span() for m in matches] == [(1, 2), (3, 5)]


def test_finditer_is_lazy():
    it = rex.compile(r"\d+").finditer("1 22 333")
    first = next(it)
    assert first.group() == "1"
    second = next(it)
    assert second.group() == "22"
    assert [m.group() for m in it] == ["333"]


def test_findall_empty_matches_advance():
    assert rex.compile("a*").findall("aab") == ["aa", "", ""]
    assert rex.compile("x*").findall("abx") == ["", "", "x", ""]
    assert rex.compile("").findall("ab") == ["", "", ""]


def test_empty_pattern():
    p = rex.compile("")
    assert p.match("abc").span() == (0, 0)
    assert p.search("abc").group() == ""
    assert p.fullmatch("") is not None
    assert p.fullmatch("a") is None


def test_empty_input():
    assert rex.compile("").search("") is not None
    assert rex.compile("a").search("") is None
    assert rex.compile("a*").match("").group() == ""
    assert rex.compile("^$").match("") is not None
    assert rex.compile("^").findall("") == [""]
    assert rex.compile("$").findall("") == [""]


def test_match_with_pos():
    p = rex.compile("b")
    assert p.match("ab", 1).span() == (1, 2)
    assert p.match("ab") is None


def test_search_with_pos_and_endpos():
    p = rex.compile(r"\d")
    assert p.search("1a2a3", 2).span() == (2, 3)
    assert p.search("1a2a3", 2, 3).span() == (2, 3)
    assert p.search("1a2a3", 3, 4) is None


def test_pattern_attributes():
    p = rex.compile("a(b)", rex.IGNORECASE)
    assert p.pattern == "a(b)"
    assert p.flags == rex.IGNORECASE
    assert p.groups == 1
    assert p.groupindex == {}


def test_match_repr_and_pattern_repr():
    assert "rex.compile" in repr(rex.compile("a"))
    m = rex.compile("a").match("a")
    assert "rex.Match" in repr(m)


def test_type_errors():
    p = rex.compile("a")
    for bad in (123, None, b"a"):
        for method in (p.search, p.match, p.fullmatch, p.findall, p.finditer):
            try:
                if method.__name__ == "finditer":
                    list(method(bad))
                else:
                    method(bad)
            except TypeError:
                pass
            else:
                raise AssertionError("expected TypeError for %r" % (bad,))
