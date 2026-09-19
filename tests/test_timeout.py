"""Catastrophic-backtracking protection via the step budget."""

import time

import pytest

import rex


def test_exponential_pattern_fails_fast():
    # Classic catastrophic case: (a+)+$ against a non-matching string.
    p = rex.compile("(a+)+$", step_limit=200_000)
    start = time.monotonic()
    with pytest.raises(rex.RegexTimeoutError):
        p.search("a" * 30 + "b")
    elapsed = time.monotonic() - start
    assert elapsed < 5.0


def test_nested_quantifier_variant():
    p = rex.compile("(a*)*$", step_limit=100_000)
    with pytest.raises(rex.RegexTimeoutError):
        p.search("a" * 25 + "!")


def test_alternation_overlap_timeout():
    p = rex.compile("(a|a)*$", step_limit=100_000)
    with pytest.raises(rex.RegexTimeoutError):
        p.search("a" * 28 + "b")


def test_timeout_is_regex_error():
    p = rex.compile("(a+)+$", step_limit=50_000)
    with pytest.raises(rex.RegexError):
        p.search("a" * 30 + "b")


def test_timeout_error_message():
    p = rex.compile("(a+)+$", step_limit=10_000)
    with pytest.raises(rex.RegexTimeoutError) as excinfo:
        p.search("a" * 30 + "b")
    message = str(excinfo.value)
    assert "step limit" in message
    assert excinfo.value.limit == 10_000


def test_default_limit_is_100m():
    assert rex.DEFAULT_STEP_LIMIT == 100_000_000
    assert rex.compile("a").step_limit == 100_000_000


def test_matching_inputs_still_work_with_small_budget():
    p = rex.compile("(a+)+$", step_limit=100_000)
    assert p.match("aaaa").group() == "aaaa"


def test_budget_is_per_search_call():
    p = rex.compile("(a+)+$", step_limit=50_000)
    for _ in range(3):
        with pytest.raises(rex.RegexTimeoutError):
            p.search("a" * 30 + "b")


def test_long_but_linear_input_is_fast():
    # Non-pathological long input must not trip the budget.
    p = rex.compile("a+b")
    assert p.search("a" * 5000 + "b").span() == (0, 5001)
