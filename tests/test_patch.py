"""Patch application tests: strict, reverse, fuzz, errors."""

import pytest

from minidiff import (
    unified_diff, apply_patch, parse_unified_diff, DiffError, reverse_patch,
)


def test_apply_roundtrip():
    a = "one\ntwo\nthree\nfour\nfive\n"
    b = "one\nTWO\nthree\nfour\n4\nfive\nsix\n"
    patch = unified_diff(a, b)
    assert apply_patch(a, patch) == b


def test_apply_empty_patch_raises():
    with pytest.raises(DiffError):
        apply_patch("a\n", "")
    with pytest.raises(DiffError):
        apply_patch("a\n", "   \n")
    with pytest.raises(DiffError):
        apply_patch("a\n", None)


def test_apply_context_mismatch_raises():
    patch = unified_diff("alpha\nbeta\ngamma\n", "alpha\nBETA\ngamma\n")
    with pytest.raises(DiffError):
        apply_patch("alpha\nXXX\ngamma\n", patch)


def test_apply_line_number_out_of_range():
    patch = unified_diff("a\nb\n", "a\nB\n")
    # Re-target at a much shorter file where the hunk cannot fit.
    patch_text = patch.replace("@@ -1,2 +1,2 @@", "@@ -9,2 +9,2 @@")
    with pytest.raises(DiffError):
        apply_patch("x\ny\n", patch_text)


def test_apply_pure_insertion_and_deletion():
    assert apply_patch("a\nc\n", unified_diff("a\nc\n", "a\nb\nc\n")) \
        == "a\nb\nc\n"
    assert apply_patch("a\nb\nc\n",
                       unified_diff("a\nb\nc\n", "a\nc\n")) == "a\nc\n"


def test_apply_empty_files():
    assert apply_patch("", unified_diff("", "x\ny\n")) == "x\ny\n"
    assert apply_patch("x\ny\n", unified_diff("x\ny\n", "")) == ""
    # An identical (empty) diff is an empty patch and must raise.
    with pytest.raises(DiffError):
        apply_patch("", unified_diff("", ""))


def test_reverse_roundtrip():
    a = "one\ntwo\nthree\n"
    b = "one\n2\nthree\nfour\n"
    patch = unified_diff(a, b)
    assert apply_patch(b, patch, reverse=True) == a


def test_reverse_patch_text_roundtrip():
    a = "h1\nh2\nh3\n"
    b = "h1\nH2\nh3\n"
    patch = unified_diff(a, b)
    reversed_text = reverse_patch(patch)
    assert apply_patch(b, reversed_text) == a
    assert reverse_patch(reversed_text) == patch


def test_multi_hunk_apply():
    a_lines = ["l%d\n" % i for i in range(40)]
    b_lines = list(a_lines)
    b_lines[2] = "head\n"
    b_lines[30] = "tail\n"
    a, b = "".join(a_lines), "".join(b_lines)
    patch = unified_diff(a, b, context=0)
    assert apply_patch(a, patch) == b
    assert apply_patch(b, patch, reverse=True) == a


def test_fuzz_applies_shifted_hunk():
    # The patch expects line 2, but unrelated lines were prepended.
    patch = unified_diff("a\nb\nc\n", "a\nB\nc\n", context=0)
    shifted = "EXTRA 1\nEXTRA 2\na\nb\nc\n"
    expected = "EXTRA 1\nEXTRA 2\na\nB\nc\n"
    with pytest.raises(DiffError):
        apply_patch(shifted, patch)  # strict mode fails
    assert apply_patch(shifted, patch, fuzz=True) == expected


def test_fuzz_integer_radius():
    patch = unified_diff("a\nb\nc\n", "a\nB\nc\n", context=0)
    shifted = "X\na\nb\nc\n"
    assert apply_patch(shifted, patch, fuzz=1) == "X\na\nB\nc\n"
    with pytest.raises(DiffError):
        apply_patch(shifted, patch, fuzz=0)


def test_fuzz_still_errors_when_context_absent():
    patch = unified_diff("a\nb\nc\n", "a\nB\nc\n", context=3)
    with pytest.raises(DiffError):
        apply_patch("totally\ndifferent\ncontent\n", patch, fuzz=True)


def test_fuzz_reverse_with_shift():
    patch = unified_diff("a\nb\nc\n", "a\nB\nc\n", context=0)
    shifted_new = "PREFIX\na\nB\nc\n"
    assert apply_patch(shifted_new, patch, reverse=True, fuzz=True) \
        == "PREFIX\na\nb\nc\n"


def test_apply_no_newline_at_end():
    a = "a\nb"
    b = "a\nB"
    patch = unified_diff(a, b)
    assert apply_patch(a, patch) == b
    assert apply_patch(b, patch, reverse=True) == a


def test_apply_rejects_multifile_patch():
    p1 = unified_diff("a\n", "b\n", fromfile="f1", tofile="f1")
    p2 = unified_diff("c\n", "d\n", fromfile="f2", tofile="f2")
    with pytest.raises(DiffError):
        apply_patch("a\n", p1 + p2)


@pytest.mark.parametrize("context", [0, 1, 3])
def test_random_roundtrips(context):
    import random
    random.seed(context * 99 + 5)
    for _ in range(40):
        a_lines = ["%d-line\n" % i for i in range(random.randint(0, 25))]
        b_lines = list(a_lines)
        edits = random.randint(0, 5)
        for _ in range(edits):
            r = random.random()
            if not b_lines and r >= 0.75:
                r = 0.2  # force an insert when empty
            if r < 0.4 and b_lines:
                pos = random.randrange(len(b_lines))
                new_text = "mod-%d\n" % random.randint(0, 100000)
                if b_lines[pos] != new_text:
                    b_lines[pos] = new_text
                else:
                    b_lines[pos] = "other-mod\n"
            elif r < 0.75:
                pos = random.randint(0, len(b_lines))
                b_lines.insert(pos, "ins-%d\n" % random.randint(0, 100000))
            elif b_lines:
                pos = random.randrange(len(b_lines))
                del b_lines[pos]
        a, b = "".join(a_lines), "".join(b_lines)
        patch = unified_diff(a, b, context=context)
        if a == b:
            assert patch == ""
            with pytest.raises(DiffError):
                apply_patch(a, patch)
            continue
        assert patch
        assert apply_patch(a, patch) == b
        assert apply_patch(b, patch, reverse=True) == a
