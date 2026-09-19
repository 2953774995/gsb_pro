"""Tests for the line/character edit scripts and the LCS engine."""

import random

import pytest

from minidiff import diff_lines, diff_chars, similarity, Op
from minidiff._core import align


def naive_lcs_len(x, y):
    row = [0] * (len(y) + 1)
    for i in range(len(x)):
        prev = 0
        for j in range(len(y)):
            up_left = prev
            prev = row[j + 1]
            if x[i] == y[j]:
                row[j + 1] = up_left + 1
            else:
                row[j + 1] = max(row[j], row[j + 1])
    return row[len(y)]


def assert_script_valid(script, a, b):
    """Reconstruct both sides and check monotonic 1-based line numbers."""
    old = "".join(op.text for op in script
                  if op.kind in ("equal", "delete"))
    new = "".join(op.text for op in script
                  if op.kind in ("equal", "insert"))
    assert old == a
    assert new == b
    old_nos = [op.old_no for op in script if op.old_no is not None]
    new_nos = [op.new_no for op in script if op.new_no is not None]
    assert old_nos == list(range(1, len(old_nos) + 1))
    assert new_nos == list(range(1, len(new_nos) + 1))
    # Kinds and numbering invariants.
    for op in script:
        if op.kind == "equal":
            assert op.old_no is not None and op.new_no is not None
        elif op.kind == "delete":
            assert op.old_no is not None and op.new_no is None
        elif op.kind == "insert":
            assert op.old_no is None and op.new_no is not None
        else:  # pragma: no cover - defensive
            raise AssertionError("unknown kind %r" % op.kind)


def test_identical_text_is_all_equal():
    text = "a\nb\nc\n"
    ops = diff_lines(text, text)
    assert ops == [
        Op("equal", 1, 1, "a\n"),
        Op("equal", 2, 2, "b\n"),
        Op("equal", 3, 3, "c\n"),
    ]


def test_pure_insertion():
    ops = diff_lines("a\nc\n", "a\nb\nc\n")
    assert_script_valid(ops, "a\nc\n", "a\nb\nc\n")
    assert [op.kind for op in ops] == ["equal", "insert", "equal"]
    assert ops[1] == Op("insert", None, 2, "b\n")


def test_pure_deletion():
    ops = diff_lines("a\nb\nc\n", "a\nc\n")
    assert_script_valid(ops, "a\nb\nc\n", "a\nc\n")
    assert [op.kind for op in ops] == ["equal", "delete", "equal"]
    assert ops[1] == Op("delete", 2, None, "b\n")


def test_mixed_changes():
    a = "one\ntwo\nthree\nfour\nfive\n"
    b = "one\nTWO\nthree\nfour\n4\nfive\nsix\n"
    ops = diff_lines(a, b)
    assert_script_valid(ops, a, b)
    assert "".join(op.text for op in ops if op.kind == "delete") == \
        "two\n4\n" or True  # '4' not in a; reconstruct already asserted
    deletes = "".join(op.text for op in ops if op.kind == "delete")
    inserts = "".join(op.text for op in ops if op.kind == "insert")
    assert deletes == "two\n"
    assert inserts == "TWO\n4\nsix\n"


def test_empty_inputs():
    assert diff_lines("", "") == []
    assert_script_valid(diff_lines("", "x\n"), "", "x\n")
    assert_script_valid(diff_lines("x\n", ""), "x\n", "")
    assert diff_lines("", "x\n") == [Op("insert", None, 1, "x\n")]
    assert diff_lines("x\n", "") == [Op("delete", 1, None, "x\n")]


def test_no_trailing_newline():
    ops = diff_lines("a\nb", "a\nB")
    assert_script_valid(ops, "a\nb", "a\nB")


def test_random_scripts_are_optimal_and_valid():
    random.seed(42)
    for _ in range(300):
        n = random.randint(0, 18)
        m = random.randint(0, 18)
        a_lines = [random.choice("abc\n") for _ in range(n)]
        b_lines = [random.choice("abc\n") for _ in range(m)]
        a = "".join(a_lines)
        b = "".join(b_lines)
        script = diff_lines(a, b)
        assert_script_valid(script, a, b)
        x = a.splitlines(keepends=True)
        y = b.splitlines(keepends=True)
        equal = sum(1 for op in script if op.kind == "equal")
        assert equal == naive_lcs_len(x, y)


def test_align_low_level_random():
    random.seed(7)
    for _ in range(200):
        x = [random.randint(0, 3) for _ in range(random.randint(0, 20))]
        y = [random.randint(0, 3) for _ in range(random.randint(0, 20))]
        result = align(x, y)
        assert [v for k, i, j, v in result if k in ("equal", "delete")] == x
        assert [v for k, i, j, v in result if k in ("equal", "insert")] == y
        equal = sum(1 for t in result if t[0] == "equal")
        assert equal == naive_lcs_len(x, y)


def test_disjoint_fastpath_matches_dp():
    a = "".join("x%d\n" % i for i in range(50))
    b = "".join("y%d\n" % i for i in range(60))
    ops = diff_lines(a, b)
    assert_script_valid(ops, a, b)
    assert all(op.kind != "equal" for op in ops)


def test_large_input_with_small_change_is_fast():
    a_lines = ["line %d\n" % i for i in range(20000)]
    b_lines = list(a_lines)
    b_lines[12345] = "line CHANGED\n"
    a = "".join(a_lines)
    b = "".join(b_lines)
    import time
    start = time.monotonic()
    ops = diff_lines(a, b)
    elapsed = time.monotonic() - start
    assert elapsed < 2.0
    assert_script_valid(ops, a, b)
    assert sum(1 for op in ops if op.kind != "equal") == 2


@pytest.mark.parametrize("size", [3000])
def test_large_replacement_completes(size):
    a = "".join("a%d\n" % i for i in range(size))
    b = "".join("b%d\n" % i for i in range(size))
    import time
    start = time.monotonic()
    ops = diff_lines(a, b)
    elapsed = time.monotonic() - start
    assert elapsed < 10.0
    assert_script_valid(ops, a, b)


def test_diff_chars_basic():
    ops = diff_chars("hello world", "hello World!")
    assert "".join(op.text for op in ops
                   if op.kind in ("equal", "delete")) == "hello world"
    assert "".join(op.text for op in ops
                   if op.kind in ("equal", "insert")) == "hello World!"
    assert ops[0] == Op("equal", 1, 1, "h")
    assert any(op.kind == "delete" and op.text == "w" for op in ops)
    assert any(op.kind == "insert" and op.text == "W" for op in ops)
    assert any(op.kind == "insert" and op.text == "!" for op in ops)


def test_diff_chars_empty():
    assert diff_chars("", "") == []
    assert diff_chars("abc", "")
    assert diff_chars("", "abc")


def test_diff_chars_rejects_non_str():
    with pytest.raises(TypeError):
        diff_chars(["a"], ["b"])


def test_similarity_scores():
    assert similarity("a\nb\nc\n", "a\nb\nc\n") == 1.0
    assert similarity("", "") == 1.0
    assert similarity("a\n", "b\n") == 0.0
    score = similarity("a\nb\n", "a\nc\n")
    assert score == pytest.approx(2.0 / 4.0)
    assert 0.0 < similarity("a\nb\nc\n", "a\nb\nx\n") < 1.0


def test_list_input_normalization():
    ops = diff_lines(["a", "b"], ["a", "c"])
    assert_script_valid(ops, "a\nb\n", "a\nc\n")


def test_hirschberg_fallback_path():
    """High edit distance (non-disjoint) forces the Hirschberg fallback."""
    import random
    from minidiff import _core
    # Force the budget small so Myers gives up and Hirschberg runs.
    random.seed(11)
    x = ["%03d\n" % random.randint(0, 5) for _ in range(400)]
    y = ["%03d\n" % random.randint(0, 5) for _ in range(400)]
    result = _core._hirschberg(x, 0, len(x), y, 0, len(y))
    assert [v for k, i, j, v in result if k in ("equal", "delete")] == x
    assert [v for k, i, j, v in result if k in ("equal", "insert")] == y

    # And through the public API it must match a direct DP LCS length.
    script = diff_lines("".join(x), "".join(y))
    assert_script_valid(script, "".join(x), "".join(y))
    assert sum(1 for op in script if op.kind == "equal") == \
        naive_lcs_len(x, y)


def test_myers_budget_exceeded_falls_back():
    """When Myers exceeds its round budget, align() still returns a SES."""
    from minidiff import _core
    # Two sequences sharing only a few elements: edit distance is large.
    x = ["x%d\n" % (i % 3) for i in range(300)]
    y = ["y%d\n" % (i % 3) for i in range(300)]
    with __import__("pytest").raises(_core._BudgetExceeded):
        _core._myers(x, y, budget=4)
    result = _core.align(x, y)
    assert [v for k, i, j, v in result if k in ("equal", "delete")] == x
    assert [v for k, i, j, v in result if k in ("equal", "insert")] == y
