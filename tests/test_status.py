"""status: staged / modified / untracked / deleted, long and --short output."""

import os

from conftest import run, write


def _prepare(repo):
    write(repo, "tracked.txt", "v1")
    write(repo, "todelete.txt", "gone soon")
    run("add", ".")
    run("commit", "-m", "init")


def test_status_three_states(repo, capsys):
    _prepare(repo)
    write(repo, "tracked.txt", "v2")          # modified, unstaged
    write(repo, "staged.txt", "s")            # staged new file
    run("add", "staged.txt")
    write(repo, "untracked.txt", "u")         # untracked
    capsys.readouterr()

    assert run("status") == 0
    out = capsys.readouterr().out
    assert "Changes to be committed:" in out
    assert "new file:   staged.txt" in out
    assert "Changes not staged for commit:" in out
    assert "modified:   tracked.txt" in out
    assert "Untracked files:" in out
    assert "untracked.txt" in out


def test_status_deleted(repo, capsys):
    _prepare(repo)
    os.remove(repo / "tracked.txt")           # will be staged deletion
    run("add", ".")                           # sync deletion into index
    os.remove(repo / "todelete.txt")          # unstaged deletion
    capsys.readouterr()

    assert run("status") == 0
    out = capsys.readouterr().out
    staged_section, rest = out.split("Changes not staged for commit:")
    assert "deleted:   tracked.txt" in staged_section
    assert "deleted:   todelete.txt" in rest


def test_status_short_format(repo, capsys):
    _prepare(repo)
    write(repo, "tracked.txt", "v2")
    write(repo, "staged.txt", "s")
    run("add", "staged.txt")
    write(repo, "untracked.txt", "u")
    capsys.readouterr()

    assert run("status", "--short") == 0
    lines = capsys.readouterr().out.splitlines()
    assert "A  staged.txt" in lines
    assert " M tracked.txt" in lines
    assert "?? untracked.txt" in lines


def test_status_clean(repo, capsys):
    _prepare(repo)
    capsys.readouterr()
    assert run("status") == 0
    assert "nothing to commit, working tree clean" in capsys.readouterr().out
