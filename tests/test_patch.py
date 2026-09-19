import pytest

from minidiff import apply_patch, parse_unified_diff, reverse_patch, unified_diff
from minidiff.patch import DiffError


def roundtrip(old, new, **kwargs):
    patch_text = unified_diff(old, new, **kwargs)
    assert apply_patch(old, patch_text) == new
    assert apply_patch(new, patch_text, reverse=True) == old
    parsed = parse_unified_diff(patch_text)
    assert apply_patch(old, parsed) == new
    assert apply_patch(new, reverse_patch(parsed)) == old
    return patch_text


def test_apply_generated_patch_roundtrip():
    old = "header\n\nold line 1\nmiddle\nold line 2\nfooter\n"
    new = "header\n\nnew line 1\nmiddle\nnew line 2\nfooter\nadded\n"
    patch = roundtrip(old, new, context=2)
    assert patch.count("@@") == 2


def test_pure_addition_and_deletion_roundtrip():
    assert roundtrip("a\n", "a\nb\nc\n", context=0)
    assert roundtrip("a\nb\nc\n", "a\n", context=0)


def test_empty_input_boundaries_roundtrip():
    assert roundtrip("", "new\n", context=0)
    assert roundtrip("old\n", "", context=0)
    assert roundtrip("", "no newline", context=0)


def test_no_newline_at_eof_and_crlf_roundtrip():
    assert roundtrip("abc", "xyz", context=0)
    assert roundtrip("abc\n", "abc", context=0)
    assert roundtrip("abc", "abc\n", context=0)
    assert roundtrip("a\r\nb\r\n", "a\r\nB\r\n", context=0)


def test_multiple_hunks_apply_and_reverse():
    old = "\n".join(f"line{i}" for i in range(1, 31)) + "\n"
    new = "\n".join(
        ("CHANGED" if i in (3, 17, 29) else f"line{i}")
        for i in range(1, 31)
    ) + "\n"
    roundtrip(old, new, context=2)


def test_context_mismatch_raises_diff_error():
    original = "one\nWRONG\nthree\n"
    patch = (
        "--- a\n+++ b\n@@ -1,3 +1,3 @@\n"
        " one\n-old\n+new\n three\n"
    )
    with pytest.raises(DiffError, match="context mismatch"):
        apply_patch(original, patch)


def test_strict_application_rejects_line_offset():
    original = "extra\ncontext\nold\nafter\n"
    patch = (
        "--- a\n+++ b\n@@ -1,3 +1,3 @@\n"
        " context\n-old\n+new\n after\n"
    )
    # Fuzzy application ignores the bad hunk coordinate and finds the anchor.
    assert apply_patch(original, patch) == "extra\ncontext\nnew\nafter\n"
    with pytest.raises(DiffError, match="context mismatch"):
        apply_patch(original, patch, fuzz=False)


def test_line_number_out_of_bounds_raises_diff_error():
    patch = (
        "--- a\n+++ b\n@@ -99 +99 @@\n-old\n+new\n"
    )
    with pytest.raises(DiffError, match="out of bounds"):
        apply_patch("old\n", patch)


def test_empty_patch_application_is_an_error():
    with pytest.raises(DiffError, match="empty patch"):
        apply_patch("anything\n", "")
    with pytest.raises(DiffError, match="empty patch"):
        apply_patch("anything\n", "--- a\n+++ b\n")


def test_patch_count_mismatch_raises_diff_error():
    patch = (
        "--- a\n+++ b\n@@ -1,2 +1,2 @@\n-old\n+new\n"
    )
    with pytest.raises(DiffError):
        parse_unified_diff(patch)


def test_reverse_structured_patch_flips_header_and_operations():
    patch = parse_unified_diff(unified_diff("a\n", "b\n", context=0))
    flipped = reverse_patch(patch)
    assert flipped.old_path == "b"
    assert flipped.new_path == "a"
    assert [line.kind for line in flipped.hunks[0].lines] == ["insert", "delete"]
