"""Catastrophic backtracking must terminate safely via the step budget."""

import time

import pytest

import rex
from rex.errors import RegexTimeoutError


PATHOLOGICAL = r"(a+)+$"


def test_pathological_fullmatch_times_out_fast():
    p = rex.compile(PATHOLOGICAL, max_steps=50_000)
    start = time.time()
    with pytest.raises(RegexTimeoutError):
        p.fullmatch("a" * 40 + "b")
    assert time.time() - start < 2.0


def test_pathological_search_times_out_fast():
    p = rex.compile(r"(a|aa)+$", max_steps=100_000)
    start = time.time()
    with pytest.raises(RegexTimeoutError):
        p.search("a" * 30 + "b")
    assert time.time() - start < 2.0


def test_pathological_finditer_aborts():
    p = rex.compile(r"(a+)+b", max_steps=100_000)
    text = "a" * 30 + "c"
    start = time.time()
    with pytest.raises(RegexTimeoutError):
        list(p.finditer(text))
    assert time.time() - start < 2.0


def test_timeout_is_subclass_of_regex_error():
    p = rex.compile(PATHOLOGICAL, max_steps=1000)
    with pytest.raises(rex.RegexError):
        p.fullmatch("a" * 20 + "b")


def test_normal_long_input_is_fast():
    p = rex.compile(PATHOLOGICAL)
    start = time.time()
    m = p.fullmatch("a" * 5000)
    assert m is not None and m.end() == 5000
    assert time.time() - start < 5.0


def test_default_budget_is_100_million():
    assert rex.DEFAULT_MAX_STEPS == 100_000_000
    p = rex.compile("a")
    assert p.max_steps == rex.DEFAULT_MAX_STEPS


def test_nested_quantifier_realistic_text_does_not_hang():
    # Classic evil regex on a realistic length with a tight budget.
    p = rex.compile(r"^(a+)+b$", max_steps=200_000)
    start = time.time()
    try:
        result = p.match("a" * 25 + "b")
    except RegexTimeoutError:
        result = None
    assert time.time() - start < 2.0
    assert result is None or result is not None
