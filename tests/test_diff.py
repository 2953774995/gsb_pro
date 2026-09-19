"""diff: opcodes, swapped lines, unified format, --stat."""

from conftest import repo, run_cli, write_file
from minigit import diff as d
from minigit import objects as obj
from minigit import refs as refs_mod


def test_opcodes_swapped_lines():
    a = ["1\n", "2\n", "3\n"]
    b = ["1\n", "3\n", "2\n"]
    ops = d.opcodes(a, b)
    # Net effect: one deletion and one insertion, never a replace-only
    removed = sum(aj - ai for op, ai, aj, _, _ in ops if op in ("delete", "replace"))
    added = sum(bj - bi for op, _, _, bi, bj in ops if op in ("insert", "replace"))
    assert added == 1 and removed == 1
    # Replaying the script transforms a into b.
    replay = []
    for op, ai, aj, bi, bj in ops:
        if op in ("equal", "insert", "replace"):
            replay.extend(b[bi:bj])
    assert replay == b


def test_unified_diff_format():
    a = b"a\nb\nc\n"
    b = b"a\nc\nd\n"
    out = d.unified_diff(a, b, "a/f", "b/f")
    assert out.startswith("--- a/f\n+++ b/f\n")
    assert "@@ -1,3 +1,3 @@" in out
    body = out.split("@@", 1)[1]
    assert " a\n" in body and " c\n" in body
    assert "-b\n" in body and "+d\n" in body
    assert out == "" or out.endswith("\n")


def test_equal_blobs_produce_empty_diff():
    assert d.unified_diff(b"x\n", b"x\n") == ""
    assert d.count_changes(b"x\n", b"x\n") == (0, 0)


def test_diff_command_worktree_vs_index(init_repo):
    write_file("f.txt", "one\ntwo\nthree\n")
    run_cli("add", ".")
    run_cli("commit", "-m", "c")
    write_file("f.txt", "one\nthree\nfour\n")  # swap-ish: drop two, add four
    code, out, err = run_cli("diff")
    assert code == 0, err
    assert "-two\n" in out and "+four\n" in out
    assert "diff --git a/f.txt b/f.txt" in out

    code, stat_out, _ = run_cli("diff", "--stat")
    assert "f.txt" in stat_out
    assert "1 insertion(s)(+)" in stat_out
    assert "1 deletion(s)(-)" in stat_out


def test_diff_cached_compares_index_to_head(init_repo):
    write_file("f.txt", "hello\n")
    run_cli("add", ".")
    run_cli("commit", "-m", "c")
    write_file("f.txt", "hello\nworld\n")
    run_cli("add", "f.txt")
    code, out, _ = run_cli("diff", "--cached")
    assert "+world\n" in out
    # worktree now matches index -> plain diff empty
    code, out2, _ = run_cli("diff")
    assert out2 == ""


def test_diff_shows_deletion_of_entire_file(init_repo):
    import os

    write_file("f.txt", "only line\n")
    run_cli("add", ".")
    run_cli("commit", "-m", "c")
    os.remove("f.txt")
    code, out, _ = run_cli("diff")
    assert "-only line\n" in out
