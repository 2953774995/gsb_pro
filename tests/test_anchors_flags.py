"""Anchors and the IgnoreCase / Multiline compile options."""

import re

import rex


def test_ignorecase_literals_and_classes():
    p = rex.compile("abc", rex.IGNORECASE)
    assert p.search("xxABCyy").group() == "ABC"
    assert p.fullmatch("AbC") is not None
    assert rex.compile("[a-z]+", rex.I).findall("Hello WORLD x") == [
        "Hello",
        "WORLD",
        "x",
    ]


def test_ignorecase_shorthands_still_work():
    assert rex.compile(r"\w+", rex.I).findall("Ab Z") == ["Ab", "Z"]


def test_multiline_start_anchor():
    text = "foo\nbar\nfoobar"
    p = rex.compile("^foo", rex.MULTILINE)
    assert [m.start() for m in p.finditer(text)] == [0, 8]
    # Without multiline only the real text start qualifies.
    assert [m.start() for m in rex.compile("^foo").finditer(text)] == [0]


def test_multiline_end_anchor_before_every_newline():
    text = "foo\nbar\nfoobar\n"
    p = rex.compile(r"\w+$", rex.MULTILINE)
    assert p.findall(text) == ["foo", "bar", "foobar"]


def test_multiline_empty_line_anchors():
    p = rex.compile("^$", rex.MULTILINE)
    assert [m.start() for m in p.finditer("a\n\nb")] == [2]


def test_multiline_dollar_matches_before_newline():
    p = rex.compile("a$", rex.MULTILINE)
    assert [m.span() for m in p.finditer("a\na")] == [(0, 1), (2, 3)]


def test_flags_combine():
    p = rex.compile("^FOO$", rex.IGNORECASE | rex.MULTILINE)
    assert p.search("xx\nfoo\n").group() == "foo"


def test_parity_with_re_on_anchor_corpus():
    patterns = ["^abc", "abc$", "^$", ".*$", "^.*$", r"\w+$"]
    texts = ["abc", "abc\n", "abc\n\n", "a\nb\nc", "x\nabc"]
    for pat in patterns:
        for flags in (0, re.M):
            assert rex.compile(pat, flags).findall(texts[0]) is not None
            for text in texts:
                assert [m.span() for m in rex.compile(pat, flags).finditer(text)] == [
                    m.span() for m in re.finditer(pat, text, flags)
                ]
