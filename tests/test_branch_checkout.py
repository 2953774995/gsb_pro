"""branch / checkout: creation, listing marker, working-tree restoration."""

import os

from conftest import read_file, repo, run_cli, write_file
from minigit import refs as refs_mod


def _commit_all(message):
    assert run_cli("add", ".")[0] == 0
    code, _, err = run_cli("commit", "-m", message)
    assert code == 0, err


def test_branch_listing_with_current_marker(init_repo):
    write_file("a", "1")
    _commit_all("c")
    code, _, err = run_cli("branch", "dev")
    assert code == 0, err
    code, out, _ = run_cli("branch")
    assert "* main" in out
    assert "  dev" in out


def test_branch_duplicate_and_branch_on_unborn_head(init_repo):
    code, _, err = run_cli("branch", "x")
    assert code == 1  # no commit yet
    write_file("a", "1")
    _commit_all("c")
    assert run_cli("branch", "x")[0] == 0
    code, _, err = run_cli("branch", "x")
    assert code == 1 and "already exists" in err


def test_checkout_overwrites_adds_and_deletes(init_repo):
    # v1 on main: keep.txt, change.txt=old, remove.txt
    write_file("keep.txt", "keep\n")
    write_file("change.txt", "old\n")
    write_file("remove.txt", "gone\n")
    _commit_all("main v1")
    assert run_cli("branch", "old")[0] == 0

    # v2 on main: change.txt overwritten, added.txt new, remove.txt deleted
    write_file("change.txt", "new\n")
    write_file("added.txt", "added\n")
    os.remove("remove.txt")
    assert run_cli("add", ".")[0] == 0
    assert run_cli("add", "remove.txt")[0] == 0  # stage the deletion
    code, _, err = run_cli("commit", "-m", "main v2")
    assert code == 0, err

    code, out, err = run_cli("checkout", "old")
    assert code == 0, err
    # overwritten back
    assert read_file("change.txt") == b"old\n"
    # tracked file deleted in v2 is restored
    assert read_file("remove.txt") == b"gone\n"
    # file added in v2 is removed from the working tree
    assert not os.path.exists("added.txt")
    # unaffected file stays
    assert read_file("keep.txt") == b"keep\n"

    # switching back restores v2 again
    code, _, err = run_cli("checkout", "main")
    assert code == 0
    assert read_file("change.txt") == b"new\n"
    assert read_file("added.txt") == b"added\n"
    assert not os.path.exists("remove.txt")


def test_checkout_preserves_untracked_files(init_repo):
    write_file("tracked.txt", "t\n")
    _commit_all("c")
    run_cli("branch", "b")
    write_file("tracked.txt", "t2\n")
    _commit_all("c2")
    write_file("untracked.txt", "u\n")
    assert run_cli("checkout", "b")[0] == 0
    assert read_file("untracked.txt") == b"u\n"  # preserved


def test_checkout_refuses_to_overwrite_untracked(init_repo):
    # A file committed on main but not tracked on b: while on b the user
    # creates an untracked file at that path; switching back must refuse.
    write_file("tracked.txt", "t\n")
    _commit_all("base")
    run_cli("branch", "b")
    write_file("only-main.txt", "committed on main\n")
    _commit_all("main-only commit")
    assert refs_mod.read_branch(repo(), "b") != refs_mod.read_branch(repo(), "main")

    assert run_cli("checkout", "b")[0] == 0
    assert not os.path.exists("only-main.txt")  # tracked file removed
    write_file("only-main.txt", "untracked blocker\n")
    code, _, err = run_cli("checkout", "main")
    assert code == 1
    assert "untracked" in err
    assert read_file("only-main.txt") == b"untracked blocker\n"


def test_checkout_unknown_branch_errors(init_repo):
    write_file("a", "1")
    _commit_all("c")
    code, _, err = run_cli("checkout", "ghost")
    assert code == 1
    assert "ghost" in err
