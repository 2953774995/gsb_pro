import os

from conftest import write


def commit_all(repo, run, msg="c"):
    assert run("add", ".") == 0
    assert run("commit", "-m", msg) == 0


def test_status_clean(repo, run, capsys):
    write(repo.root, "a.txt", "a")
    commit_all(repo, run)
    assert run("status") == 0
    out = capsys.readouterr().out
    assert "nothing to commit" in out


def test_status_three_states(repo, run, capsys):
    write(repo.root, "staged.txt", "v1")
    write(repo.root, "modified.txt", "v1")
    commit_all(repo, run)

    # staged: index differs from HEAD
    write(repo.root, "staged.txt", "v2")
    assert run("add", "staged.txt") == 0
    # modified: worktree differs from index
    write(repo.root, "modified.txt", "v2")
    # untracked
    write(repo.root, "new.txt", "untracked")

    assert run("status") == 0
    out = capsys.readouterr().out
    staged_section = out.split("Changes to be committed:")[1]
    assert "staged.txt" in staged_section.split("Changes not staged")[0]
    assert "modified:   modified.txt" in out
    assert "new.txt" in out.split("Untracked files:")[1]


def test_status_deleted(repo, run, capsys):
    write(repo.root, "gone.txt", "bye")
    write(repo.root, "staged_gone.txt", "bye too")
    commit_all(repo, run)

    # deleted in worktree only -> unstaged deletion
    os.remove(os.path.join(repo.root, "gone.txt"))
    # staged deletion: remove from index via reset-like rebuild
    from minigit import index as indexmod
    entries = indexmod.read_index(repo)
    del entries["staged_gone.txt"]
    indexmod.write_index(repo, entries)

    assert run("status") == 0
    out = capsys.readouterr().out
    staged = out.split("Changes to be committed:")[1].split("Changes not staged")[0]
    unstaged = out.split("Changes not staged for commit:")[1]
    assert "deleted:   staged_gone.txt" in staged
    assert "deleted:   gone.txt" in unstaged


def test_status_short(repo, run, capsys):
    write(repo.root, "a.txt", "1")
    commit_all(repo, run)
    write(repo.root, "a.txt", "2")
    write(repo.root, "b.txt", "new")
    assert run("add", "b.txt") == 0
    assert run("status", "--short") == 0
    out = capsys.readouterr().out.splitlines()
    assert " M a.txt" in out
    assert "A  b.txt" in out


def test_status_no_commits_yet(repo, run, capsys):
    write(repo.root, "a.txt", "1")
    assert run("add", ".") == 0
    assert run("status") == 0
    out = capsys.readouterr().out
    assert "No commits yet" in out
    assert "new file:   a.txt" in out
