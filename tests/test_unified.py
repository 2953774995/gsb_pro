"""Unified diff rendering and parsing tests."""

import difflib
import random

import pytest

from minidiff import unified_diff, parse_unified_diff, DiffError
from minidiff.unified import HunkLine


TEXT_A = "\n".join(
    ["l0", "l1", "l2", "l3", "l4", "l5", "l6", "l7", "l8", "l9"]) + "\n"
TEXT_B = "\n".join(
    ["l0", "l1", "l2", "CHANGED", "l4", "l5",
     "l6", "l7", "l8", "l9", "l10"]) + "\n"


def test_basic_unified_diff_shape():
    out = unified_diff(TEXT_A, TEXT_B)
    assert out.startswith("--- a\n+++ b\n")
    # Both edits are within 6 lines of each other so they share one hunk.
    assert "@@ -1,10 +1,11 @@\n" in out
    assert "-l3\n" in out
    assert "+CHANGED\n" in out
    assert "+l10\n" in out
    assert out.endswith("+l10\n")


def test_identical_text_produces_empty_diff():
    assert unified_diff("a\nb\n", "a\nb\n") == ""


def test_context_parameter():
    c0 = unified_diff(TEXT_A, TEXT_B, context=0)
    assert c0.count("@@ -") == 2
    assert "@@ -4 +4 @@\n" in c0  # single-line range omits length
    assert "@@ -10,0 +11 @@\n" in c0
    c1 = unified_diff(TEXT_A, TEXT_B, context=1)
    assert "@@ -3,3 +3,3 @@" in c1
    assert "@@ -10 +10,2 @@" in c1


def test_invalid_context_rejected():
    with pytest.raises(ValueError):
        unified_diff("a\n", "b\n", context=-1)


def test_multiple_hunks():
    a_lines = ["l%d\n" % i for i in range(40)]
    b_lines = list(a_lines)
    b_lines[2] = "head-change\n"
    b_lines[30] = "tail-change\n"
    a, b = "".join(a_lines), "".join(b_lines)
    out = unified_diff(a, b, context=3)
    assert out.count("@@ -") == 2
    patch = parse_unified_diff(out)
    assert len(patch.hunks) == 2
    assert patch.hunks[0].old_start == 1
    assert patch.hunks[1].old_start == 28


def test_hunks_merge_when_close():
    a_lines = ["l%d\n" % i for i in range(20)]
    b_lines = list(a_lines)
    b_lines[2] = "x\n"
    b_lines[3] = "y\n"  # adjacent change -> still one hunk
    out = unified_diff("".join(a_lines), "".join(b_lines), context=3)
    assert out.count("@@ -") == 1


def test_parse_roundtrip_structured():
    out = unified_diff(TEXT_A, TEXT_B, context=2)
    patch = parse_unified_diff(out)
    assert patch.fromfile == "a"
    assert patch.tofile == "b"
    hunk = patch.hunks[0]
    kinds = "".join(hl.kind for hl in hunk.lines)
    assert kinds == "  -+  "
    assert hunk.lines[2] == HunkLine("-", "l3\n")
    assert hunk.lines[3] == HunkLine("+", "CHANGED\n")


def test_parse_and_render_is_stable():
    for context in (0, 1, 3, 5):
        out = unified_diff(TEXT_A, TEXT_B, context=context)
        patch = parse_unified_diff(out)
        from minidiff.unified import render_patch
        assert render_patch(patch) == out


def test_insertion_only_hunk_headers():
    a = "a\nb\nc\n"
    b = "x\na\nb\nc\n"
    out = unified_diff(a, b, context=0)
    assert "@@ -0,0 +1 @@" in out
    parsed = parse_unified_diff(out)
    from minidiff.unified import render_patch
    assert render_patch(parsed) == out


def test_empty_file_diff():
    out = unified_diff("", "new line\n")
    assert "@@ -0,0 +1 @@" in out
    assert out.count("@@ -") == 1
    patch = parse_unified_diff(out)
    assert patch.hunks[0].old_len == 0
    assert patch.hunks[0].new_len == 1


def test_delete_entire_file():
    out = unified_diff("a\nb\n", "")
    assert "@@ -1,2 +0,0 @@" in out
    patch = parse_unified_diff(out)
    assert patch.hunks[0].new_len == 0


def test_no_newline_marker_roundtrip():
    a = "a\nb"
    b = "a\nB"
    out = unified_diff(a, b)
    assert "\\ No newline at end of file\n" in out
    patch = parse_unified_diff(out)
    changed = [hl for hl in patch.hunks[0].lines if hl.kind != " "]
    assert all(hl.no_newline for hl in changed)
    from minidiff.unified import render_patch
    assert render_patch(patch) == out


def test_against_difflib_random_inputs():
    """Generated output must match the stdlib reference implementation."""
    random.seed(1234)
    for _ in range(120):
        n = random.randint(0, 30)
        a = ["line %d %s\n" % (i, random.choice("xyz"))
             for i in range(n)]
        b = [line for line in a]
        for _ in range(random.randint(0, 4)):
            if not b and random.random() < 0.5:
                b.insert(0, "fresh\n")
                continue
            pos = random.randint(0, max(0, len(b) - 1))
            choice = random.random()
            if choice < 0.4 and b:
                b[pos] = "changed-%d\n" % random.randint(0, 9999)
            elif choice < 0.7:
                b.insert(pos, "inserted-%d\n" % random.randint(0, 9999))
            elif b:
                del b[pos]
        context = random.randint(0, 5)
        expected = "".join(difflib.unified_diff(
            a, b, "a", "b", n=context, lineterm="\n"))
        actual = unified_diff("".join(a), "".join(b),
                              context=context)
        assert actual == expected


def test_parse_errors():
    with pytest.raises(DiffError):
        parse_unified_diff("")
    with pytest.raises(DiffError):
        parse_unified_diff("nothing to see here\n")
    bad_header = "--- a\n+++ b\n@@ -1,5 +1,5 @@\n x\n"
    with pytest.raises(DiffError):
        parse_unified_diff(bad_header)
    bad_marker = "--- a\n+++ b\n@@ -1 +1 @@\n\\ No newline at end of file\n"
    with pytest.raises(DiffError):
        parse_unified_diff(bad_marker)


def test_parse_multifile_patch():
    p1 = unified_diff("a\n", "b\n", fromfile="f1", tofile="f1")
    p2 = unified_diff("c\n", "d\n", fromfile="f2", tofile="f2")
    patch = parse_unified_diff(p1 + p2)
    assert [f[0] for f in patch.files] == ["f1", "f2"]


def test_custom_filenames():
    out = unified_diff("a\n", "b\n", fromfile="old.txt", tofile="new.txt")
    assert out.startswith("--- old.txt\n+++ new.txt\n")
    patch = parse_unified_diff(out)
    assert (patch.fromfile, patch.tofile) == ("old.txt", "new.txt")
