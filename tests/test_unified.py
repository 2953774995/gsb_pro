import pytest

from minidiff import unified_diff
from minidiff.diff import EQUAL, INSERT
from minidiff.patch import DiffError
from minidiff.unified import (
    Hunk,
    HunkLine,
    Patch,
    parse_unified_diff,
    render_patch,
)


def test_unified_diff_basic_format():
    patch = unified_diff("a\nb\nc\n", "a\nB\nc\n")
    assert patch.splitlines() == [
        "--- a",
        "+++ b",
        "@@ -1,3 +1,3 @@",
        " a",
        "-b",
        "+B",
        " c",
    ]


def test_identical_text_is_empty_patch():
    assert unified_diff("same\n", "same\n") == ""


def test_pure_addition_and_deletion_hunk_headers():
    addition = unified_diff("a\n", "a\nb\n", context=0)
    assert "@@ -1,0 +2 @@" in addition
    assert "+b" in addition

    deletion = unified_diff("a\nb\n", "b\n", context=0)
    assert "@@ -1 +0,0 @@" in deletion
    assert "-a" in deletion


def test_multiple_hunks_and_context_merge_rules():
    old = "\n".join(f"line{i}" for i in range(1, 21)) + "\n"
    new_lines = [
        ("CHANGED" if i in (2, 15) else f"line{i}") for i in range(1, 21)
    ]
    new = "\n".join(new_lines) + "\n"

    zero = parse_unified_diff(unified_diff(old, new, context=0))
    assert [h.old_start for h in zero.hunks] == [2, 15]

    three = parse_unified_diff(unified_diff(old, new, context=3))
    assert len(three.hunks) == 2
    assert three.hunks[0].old_start == 1
    assert three.hunks[0].old_count == 5
    assert three.hunks[1].old_start == 12
    assert three.hunks[1].old_count == 7

    six = parse_unified_diff(unified_diff(old, new, context=6))
    assert len(six.hunks) == 1
    assert six.hunks[0].old_start == 1
    assert six.hunks[0].old_count == 20


def test_zero_context_does_not_include_context_lines():
    patch = parse_unified_diff(
        unified_diff("keep\nold\nkeep\n", "keep\nnew\nkeep\n", context=0)
    )
    assert len(patch.hunks) == 1
    assert [line.kind for line in patch.hunks[0].lines] == ["delete", "insert"]


def test_parse_render_roundtrip_preserves_patch():
    old = "one\ntwo\nthree"
    new = "one\nTWO\nthree\nfour\n"
    text = unified_diff(old, new, context=2, fromfile="old.txt", tofile="new.txt")
    parsed = parse_unified_diff(text)
    assert parsed.old_path == "old.txt"
    assert parsed.new_path == "new.txt"
    assert render_patch(parsed) == text


def test_parse_handles_default_single_hunk_count_and_no_newline_marker():
    text = (
        "--- old\n+++ new\n@@ -1 +1 @@\n"
        "-abc\n\\ No newline at end of file\n"
        "+ABC\n"
    )
    patch = parse_unified_diff(text)
    assert patch.hunks[0].old_count == 1
    assert patch.hunks[0].new_count == 1
    assert patch.hunks[0].lines[0].has_newline is False
    assert patch.hunks[0].lines[1].has_newline is True


def test_parser_rejects_bad_hunk_header_and_body():
    with pytest.raises(DiffError):
        parse_unified_diff("--- a\n+++ b\n@@ bad @@\n+x\n")
    with pytest.raises(DiffError):
        parse_unified_diff("--- a\n+++ b\n@@ -1 +1 @@\n?bad\n")
    with pytest.raises(DiffError):
        parse_unified_diff("--- a\n+++ b\n@@ -2 +2 @@\n+x\n")


def test_empty_and_header_only_patch_parse_as_empty_patch():
    assert parse_unified_diff("").hunks == ()
    parsed = parse_unified_diff("--- a\n+++ b\n")
    assert isinstance(parsed, Patch)
    assert parsed.hunks == ()


def test_insertion_at_file_start_header():
    parsed = parse_unified_diff(unified_diff("", "x\n", context=0))
    hunk = parsed.hunks[0]
    assert (hunk.old_start, hunk.old_count) == (0, 0)
    assert (hunk.new_start, hunk.new_count) == (1, 1)
    assert hunk.lines == (HunkLine(INSERT, "x", True),)


def test_parser_accepts_gnu_timestamp_headers():
    text = (
        "--- old.txt\t2026-09-20 10:00:00.000000000 +0800\n"
        "+++ new.txt\t2026-09-20 10:01:00.000000000 +0800\n"
        "@@ -1 +1 @@\n"
        "-old\n+new\n"
    )
    patch = parse_unified_diff(text)
    assert patch.old_path == "old.txt"
    assert patch.new_path == "new.txt"


def test_structured_patch_construction():
    patch = Patch(
        "a",
        "b",
        [Hunk(1, 1, 1, 1, [HunkLine(EQUAL, "x", True)])],
    )
    assert " x" in render_patch(patch)
