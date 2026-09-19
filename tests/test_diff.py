import os

from conftest import write


def commit_all(repo, run, msg="c"):
    assert run("add", ".") == 0
    assert run("commit", "-m", msg) == 0


def test_diff_modified_file(repo, run, capsys):
    write(repo.root, "a.txt", "line1\nline2\nline3\n")
    commit_all(repo, run)
    write(repo.root, "a.txt", "line1\nline2 changed\nline3\n")
    assert run("diff") == 0
    out = capsys.readouterr().out
    assert "diff --minigit a/a.txt b/a.txt" in out
    assert "--- a/a.txt" in out
    assert "+++ b/a.txt" in out
    assert "@@" in out
    assert "-line2" in out
    assert "+line2 changed" in out
    assert " line1" in out  # context lines present


def test_diff_swapped_lines(repo, run, capsys):
    old = "alpha\nbeta\ngamma\n"
    new = "gamma\nbeta\nalpha\n"
    write(repo.root, "s.txt", old)
    commit_all(repo, run)
    write(repo.root, "s.txt", new)
    assert run("diff") == 0
    out = capsys.readouterr().out
    assert "@@" in out
    # Applying the +/- lines of the diff to the old content must
    # reproduce the new content exactly (alignment-independent check).
    body = [l for l in out.splitlines()
            if l and l[0] in " +-" and not l.startswith("@@")
            and not l.startswith("+++") and not l.startswith("---")]
    assert any(l.startswith("+") for l in body)
    assert any(l.startswith("-") for l in body)
    applied = [l[1:] for l in body if not l.startswith("-")]
    assert "\n".join(applied) + "\n" == new


def test_diff_added_and_deleted_lines(repo, run, capsys):
    write(repo.root, "f.txt", "a\nb\nc\nd\ne\n")
    commit_all(repo, run)
    write(repo.root, "f.txt", "a\nx\ny\nc\ne\n")
    assert run("diff") == 0
    out = capsys.readouterr().out
    assert "+x" in out and "+y" in out
    assert "-b" in out and "-d" in out


def test_diff_deleted_file(repo, run, capsys):
    write(repo.root, "d.txt", "gone\n")
    commit_all(repo, run)
    os.remove(os.path.join(repo.root, "d.txt"))
    assert run("diff") == 0
    out = capsys.readouterr().out
    assert "+++ /dev/null" in out
    assert "-gone" in out


def test_diff_clean_is_empty(repo, run, capsys):
    write(repo.root, "a.txt", "same\n")
    commit_all(repo, run)
    capsys.readouterr()  # drain add/commit output
    assert run("diff") == 0
    assert capsys.readouterr().out == ""


def test_diff_cached(repo, run, capsys):
    write(repo.root, "a.txt", "v1\n")
    commit_all(repo, run)
    write(repo.root, "a.txt", "v2\n")
    assert run("add", "a.txt") == 0
    assert run("diff", "--cached") == 0
    out = capsys.readouterr().out
    assert "-v1" in out and "+v2" in out
    # Default diff (worktree vs index) is now clean.
    assert run("diff") == 0
    assert capsys.readouterr().out == ""


def test_diff_stat(repo, run, capsys):
    write(repo.root, "a.txt", "1\n2\n3\n4\n5\n")
    commit_all(repo, run)
    write(repo.root, "a.txt", "1\n2\n3\n4\n5\n6\n7\n")
    assert run("diff", "--stat") == 0
    out = capsys.readouterr().out
    assert "a.txt" in out
    assert "+2 -0" in out
    assert "1 file(s) changed, 2 insertions(+), 0 deletions(-)" in out


def test_diff_against_commit(repo, run, capsys):
    write(repo.root, "a.txt", "old\n")
    commit_all(repo, run, "first")
    from minigit import refs
    first = refs.head_commit(repo)
    write(repo.root, "a.txt", "new\n")
    commit_all(repo, run, "second")
    assert run("diff", first) == 0
    out = capsys.readouterr().out
    assert "-old" in out and "+new" in out
