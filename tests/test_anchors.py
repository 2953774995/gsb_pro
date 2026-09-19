"""Anchors (^ $) and word boundaries (\\b \\B)."""

import regexlab


def test_start_anchor_with_search():
    assert regexlab.search("^abc", "abc") is not None
    assert regexlab.search("^abc", "xabc") is None


def test_end_anchor_with_search():
    assert regexlab.search("abc$", "abc") is not None
    assert regexlab.search("abc$", "abcx") is None


def test_both_anchors_equal_fullmatch():
    assert regexlab.search("^a.c$", "abc") is not None
    assert regexlab.search("^a.c$", "abcx") is None
    assert regexlab.search("^a.c$", "xabc") is None


def test_anchor_inside_pattern():
    m = regexlab.search(r"^a+b$", "aaab")
    assert m is not None


def test_word_boundary():
    m = regexlab.search(r"\bcat\b", "the cat sat")
    assert m.span() == (4, 7)
    assert regexlab.search(r"\bcat\b", "concatenate") is None


def test_word_boundary_at_string_edges():
    assert regexlab.search(r"\bcat", "cat") is not None
    assert regexlab.search(r"cat\b", "cat") is not None
    assert regexlab.search(r"\bcat\b", "scatter") is None


def test_non_word_boundary():
    m = regexlab.search(r"\Bcat", "scatter")
    assert m is not None
    assert m.span() == (1, 4)
    assert regexlab.search(r"\Bcat", "cat") is None


def test_boundary_between_word_and_space():
    m = regexlab.search(r"foo\b", "foo bar")
    assert m is not None
    assert regexlab.search(r"foo\b", "foobar") is None


def test_non_boundary_between_non_word_chars():
    # In "a!!b", position 2 sits between two "!" (both non-word) -> \B.
    m = regexlab.search(r"\B!", "a!!b")
    assert m is not None
    assert m.span() == (2, 3)
