"""status: staged / modified / untracked / deleted states."""

import os

from conftest import read_file, repo, run_cli, write_file
from minigit.status import compute_status, short_codes


def _first_commit():
    assert run_cli("add", ".")[0] == 0
    assert run_cli("commit", "-m", "c")[0] == 0


def test_clean_status(init_repo):
    write_file("a", "1")
    _first_commit()
    code, out, _ = run_cli("status")
    assert "working tree clean" in out
    code, out, _ = run_cli("status", "--short")
    assert out == ""


def test_three_states_and_deleted(init_repo):
    write_file("staged.txt", "s1\n")
    write_file("modified.txt", "m\n")
    write_file("deleted.txt", "d\n")
    _first_commit()

    # staged change (already committed, so make a new staged edit)
    write_file("staged.txt", "s2\n")
    run_cli("add", "staged.txt")
    # worktree modification
    write_file("modified.txt", "m-changed\n")
    # deletion
    os.remove("deleted.txt")
    # untracked
    write_file("new.txt", "n\n")

    st = compute_status(repo())
    assert set(st["staged"]) == {"staged.txt"}
    assert set(st["worktree"]) == {"modified.txt", "deleted.txt"}
    assert set(st["untracked"]) == {"new.txt"}
    assert st["worktree"]["deleted.txt"][0] == "D"
    assert st["worktree"]["modified.txt"][0] == "M"

    code, out, _ = run_cli("status", "-s")
    assert "M  staged.txt" in out
    assert " M modified.txt" in out
    assert " D deleted.txt" in out
    assert "?? new.txt" in out

    code, long, _ = run_cli("status")
    assert "Changes to be committed" in long
    assert "Changes not staged" in long
    assert "Untracked files" in long


def test_staged_deletion(init_repo):
    write_file("gone.txt", "bye\n")
    _first_commit()
    os.remove("gone.txt")
    run_cli("add", "gone.txt")
    code, out, _ = run_cli("status", "-s")
    assert "D  gone.txt" in out


def test_staged_add_is_code_A(init_repo):
    write_file("only.txt", "x\n")
    run_cli("add", "only.txt")
    st = compute_status(repo())
    assert st["staged"]["only.txt"][0] == "A"
