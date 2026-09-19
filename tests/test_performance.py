"""Catastrophic-backtracking protection via the configurable step limit."""
import time

import pytest

import rex
from rex import RegexError, RegexTimeoutError


def test_default_step_limit_is_100m():
    assert rex.DEFAULT_MAX_STEPS == 100_000_000
    assert rex.compile("a").max_steps == rex.DEFAULT_MAX_STEPS


def test_catastrophic_nested_plus_fails_fast():
    pat = rex.compile("(a+)+$", max_steps=200_000)
    start = time.monotonic()
    with pytest.raises(RegexTimeoutError):
        pat.search("a" * 30 + "b")
    elapsed = time.monotonic() - start
    assert elapsed < 5.0, "took too long: {:.2f}s".format(elapsed)


def test_catastrophic_nested_star():
    pat = rex.compile("(a*)*$", max_steps=100_000)
    with pytest.raises(RegexTimeoutError):
        pat.search("a" * 25 + "!")


def test_catastrophic_alternation_overlap():
    pat = rex.compile("(a|a)+$", max_steps=100_000)
    with pytest.raises(RegexTimeoutError):
        pat.match("a" * 28 + "b")


def test_timeout_is_regex_error():
    pat = rex.compile("(a+)+$", max_steps=10_000)
    with pytest.raises(RegexError):  # RegexTimeoutError subclasses RegexError
        pat.search("a" * 20 + "b")


def test_same_pattern_succeeds_on_matching_input():
    pat = rex.compile("(a+)+$")
    m = pat.search("aaaa")
    assert m.group() == "aaaa"
    assert m.group(1) == "aaaa"


def test_step_limit_is_configurable():
    small = rex.compile("(a+)+$", max_steps=1_000)
    with pytest.raises(RegexTimeoutError):
        small.search("a" * 15 + "b")
    # a larger budget still terminates, just later
    bigger = rex.compile("(a+)+$", max_steps=2_000_000)
    with pytest.raises(RegexTimeoutError):
        bigger.search("a" * 22 + "b")


def test_invalid_max_steps():
    with pytest.raises(RegexError):
        rex.compile("a", max_steps=0)


def test_long_input_linear_patterns_do_not_blow_stack():
    # iterative repeat/concat: no RecursionError on long inputs
    text = "x" * 100_000
    assert rex.compile("x*").fullmatch(text) is not None
    assert rex.compile("(x|y)*").fullmatch(text) is not None
    assert rex.compile("[xy]*").fullmatch(text) is not None
    assert len(rex.compile(".").findall("ab" * 10_000)) == 20_000
