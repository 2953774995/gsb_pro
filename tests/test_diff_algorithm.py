import random
import time
from itertools import product

import pytest

from minidiff.diff import (
    DELETE,
    EQUAL,
    INSERT,
    _diff_sequence,
    _hirschberg,
    _lcs_row,
    char_diff,
    diff_lines,
    similarity,
    split_text_lines,
)


def replay(ops):
    """Validate a line operation stream and return the reconstructed B lines."""

    old_count = sum(1 for op in ops if op.kind != INSERT)
    new_count = sum(1 for op in ops if op.kind != DELETE)
    for old_index, op in enumerate(
        (op for op in ops if op.kind != INSERT), start=1
    ):
        assert op.old_start == op.old_end == old_index
        assert op.new_start is None if op.kind == DELETE else True
    for new_index, op in enumerate(
        (op for op in ops if op.kind != DELETE), start=1
    ):
        assert op.new_start == op.new_end == new_index
        if op.kind == INSERT:
            assert op.old_start is None
    assert all(
        op.old_start is None or 1 <= op.old_start <= old_count
        for op in ops
    )
    assert all(
        op.new_start is None or 1 <= op.new_start <= new_count
        for op in ops
    )
    return [op.value for op in ops if op.kind != DELETE]


def lcs_edit_distance(a, b):
    previous = [0] * (len(b) + 1)
    for av in a:
        current = [0]
        for j, bv in enumerate(b, start=1):
            if av == bv:
                current.append(previous[j - 1] + 1)
            else:
                current.append(max(previous[j], current[j - 1]))
        previous = current
    return len(a) + len(b) - 2 * previous[-1]


def test_identical_text_produces_empty_change_set():
    text = "a\nb\nc\n"
    ops = diff_lines(text, text)
    assert ops
    assert all(op.kind == EQUAL for op in ops)
    assert [op for op in ops if op.kind != EQUAL] == []
    assert diff_lines("", "") == []
    assert similarity(text, text) == 1.0
    assert similarity("", "") == 1.0


def test_pure_addition_and_deletion_positions_and_content():
    old = "a\nc\n"
    new = "a\nb\nc\n"
    added = diff_lines(old, new)
    assert [(op.kind, op.value) for op in added] == [
        (EQUAL, "a\n"),
        (INSERT, "b\n"),
        (EQUAL, "c\n"),
    ]
    assert replay(added) == split_text_lines(new)

    removed = diff_lines(new, old)
    assert [(op.kind, op.value) for op in removed] == [
        (EQUAL, "a\n"),
        (DELETE, "b\n"),
        (EQUAL, "c\n"),
    ]
    assert replay(removed) == split_text_lines(old)


def test_mixed_change_uses_shortest_edit_script():
    a = "alpha\nbeta\ngamma\ndelta\n"
    b = "alpha\nBETA\ngamma\nDELTA\nend\n"
    ops = diff_lines(a, b)
    changes = [op for op in ops if op.kind != EQUAL]
    assert [op.value for op in changes] == [
        "beta\n",
        "BETA\n",
        "delta\n",
        "DELTA\n",
        "end\n",
    ]
    assert replay(ops) == split_text_lines(b)
    assert len(changes) == lcs_edit_distance(
        split_text_lines(a), split_text_lines(b)
    )


@pytest.mark.parametrize("algorithm", [_diff_sequence, _hirschberg])
def test_sequence_algorithms_are_optimal_for_small_inputs(algorithm):
    rng = random.Random(426)
    for n, m in product(range(0, 7), repeat=2):
        for _ in range(30):
            a = tuple(rng.choice("ab") for _ in range(n))
            b = tuple(rng.choice("ab") for _ in range(m))
            ops = algorithm(a, b)
            edits = sum(kind != EQUAL for kind, _ in ops)

            assert edits == lcs_edit_distance(a, b)
            # Reconstruct b.
            i = j = 0
            rebuilt = []
            for kind, value in ops:
                if kind == EQUAL:
                    assert a[i] == b[j] == value
                    i += 1
                    j += 1
                    rebuilt.append(value)
                elif kind == DELETE:
                    assert a[i] == value
                    i += 1
                else:
                    assert b[j] == value
                    j += 1
                    rebuilt.append(value)
            assert (i, j) == (n, m)
            assert rebuilt == list(b)


def test_similarity_definition():
    assert similarity("a\nb\nc\n", "a\nX\nc\n") == 2 / 3
    assert similarity("", "a\n") == 0.0
    assert similarity(["one", "two"], ["one", "two"]) == 1.0


def test_character_diff_offsets_and_replay():
    ops = char_diff("abc", "axc")
    assert [(op.kind, op.value) for op in ops] == [
        (EQUAL, "a"),
        (DELETE, "b"),
        (INSERT, "x"),
        (EQUAL, "c"),
    ]
    assert [op.value for op in ops if op.kind != DELETE] == list("axc")
    assert [(op.old_start, op.new_start) for op in ops] == [
        (0, 0),
        (1, None),
        (None, 1),
        (2, 2),
    ]


def test_large_near_identical_input_is_fast():
    old = [f"line {i}\n" for i in range(5000)]
    new = list(old)
    for index in (0, 1000, 2500, 4999):
        new[index] = f"changed {index}\n"
    new.insert(3000, "inserted\n")
    start = time.perf_counter()
    ops = diff_lines(old, new)
    elapsed = time.perf_counter() - start
    assert replay(ops) == new
    assert elapsed < 2.0


def test_large_adversarial_input_uses_linear_space_fallback_and_completes():
    # Force the Hirschberg fallback to make sure the capped-Myers path is
    # actually exercised and remains quadratic in time but linear in space.
    rng = random.Random(99)
    a = [f"{rng.getrandbits(64)}\n" for _ in range(900)]
    b = [f"{rng.getrandbits(64)}\n" for _ in range(900)]
    start = time.perf_counter()
    ops = diff_lines(a, b)
    elapsed = time.perf_counter() - start
    assert replay(ops) == b
    assert len([op for op in ops if op.kind == EQUAL]) == 0
    assert elapsed < 3.0


def test_lcs_row_basic():
    assert _lcs_row(tuple("abc"), tuple("ac")) == [0, 1, 2]
