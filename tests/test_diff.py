"""diff: unified output, --stat, --cached, deletions and additions."""

import os

from conftest import run, write


def test_diff_modified_file(repo, capsys):
    write(repo, "f.txt", "line1\nline2\nline3\n")
    run("add", ".")
    run("commit", "-m", "c1")
    # swap two lines
    write(repo, "f.txt", "line1\nline3\nline2\n")
    capsys.readouterr()

    assert run("diff") == 0
    out = capsys.readouterr().out
    assert "diff --minigit a/f.txt b/f.txt" in out
    assert "--- a/f.txt" in out
    assert "+++ b/f.txt" in out
    assert "@@" in out
    # a line swap must produce a symmetric add/remove of the swapped lines
    removed = [l[1:] for l in out.splitlines()
               if l.startswith("-") and not l.startswith("---")]
    added = [l[1:] for l in out.splitlines()
             if l.startswith("+") and not l.startswith("+++")]
    assert removed and added
    assert sorted(removed) == sorted(added)
    assert set(removed) <= {"line2", "line3"}
    # context lines are present and unprefixed
    assert " line1" in out


def test_diff_stat(repo, capsys):
    write(repo, "f.txt", "line1\nline2\nline3\n")
    run("add", ".")
    run("commit", "-m", "c1")
    write(repo, "f.txt", "line1\nline3\nline2\n")  # 1 del + 1 add
    capsys.readouterr()

    assert run("diff", "--stat") == 0
    out = capsys.readouterr().out
    assert "f.txt | 2" in out
    assert "1 insertion(s)(+)" in out
    assert "1 deletion(s)(-)" in out


def test_diff_deleted_file(repo, capsys):
    write(repo, "f.txt", "a\nb\nc\n")
    run("add", ".")
    run("commit", "-m", "c1")
    os.remove(repo / "f.txt")
    capsys.readouterr()

    assert run("diff") == 0
    out = capsys.readouterr().out
    assert "+++ /dev/null" in out
    assert "-a" in out and "-b" in out and "-c" in out


def test_diff_cached_new_file(repo, capsys):
    write(repo, "f.txt", "x\n")
    run("add", ".")
    run("commit", "-m", "c1")
    write(repo, "new.txt", "n1\nn2\n")
    run("add", "new.txt")
    capsys.readouterr()

    assert run("diff", "--cached") == 0
    out = capsys.readouterr().out
    assert "--- /dev/null" in out
    assert "+++ b/new.txt" in out
    assert "+n1" in out and "+n2" in out


def test_diff_no_changes_empty_output(repo, capsys):
    write(repo, "f.txt", "x\n")
    run("add", ".")
    run("commit", "-m", "c1")
    capsys.readouterr()
    assert run("diff") == 0
    assert capsys.readouterr().out == ""


def test_diff_hunk_headers_have_line_numbers(repo, capsys):
    body = "".join("line%d\n" % i for i in range(1, 21))
    write(repo, "f.txt", body)
    run("add", ".")
    run("commit", "-m", "c1")
    write(repo, "f.txt", body.replace("line10\n", "line10 changed\n"))
    capsys.readouterr()

    assert run("diff") == 0
    out = capsys.readouterr().out
    assert "@@ -" in out and "@@" in out
    assert "-line10" in out
    assert "+line10 changed" in out
