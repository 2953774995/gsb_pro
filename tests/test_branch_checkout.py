"""branch / checkout: branch listing, creation, workspace switching."""

import os

from conftest import head_sha, run, write


def test_branch_list_and_create(repo, capsys):
    write(repo, "a.txt", "x")
    run("add", ".")
    run("commit", "-m", "c1")
    assert run("branch", "feature") == 0
    capsys.readouterr()
    assert run("branch") == 0
    out = capsys.readouterr().out
    assert "* main" in out
    assert "  feature" in out
    # duplicate branch name rejected
    assert run("branch", "feature") != 0
    assert "already exists" in capsys.readouterr().err


def test_branch_before_any_commit_fails(repo, capsys):
    assert run("branch", "feature") != 0
    assert "no commits yet" in capsys.readouterr().err


def test_checkout_switches_workspace_add_modify_delete(repo):
    # base commit on main
    write(repo, "keep.txt", "keep")
    write(repo, "mod.txt", "v1")
    write(repo, "gone.txt", "bye")
    run("add", ".")
    run("commit", "-m", "base")

    run("branch", "feature")
    assert run("checkout", "feature") == 0
    # on feature: modify, add new, delete
    write(repo, "mod.txt", "v2")
    write(repo, "new.txt", "brand new")
    os.remove(repo / "gone.txt")
    run("add", ".")
    run("commit", "-m", "feature work")

    # back to main: workspace must be fully restored
    assert run("checkout", "main") == 0
    assert (repo / "mod.txt").read_text() == "v1"          # overwritten
    assert not (repo / "new.txt").exists()                 # deleted
    assert (repo / "gone.txt").read_text() == "bye"        # restored
    assert (repo / "keep.txt").read_text() == "keep"

    # and forward to feature again
    assert run("checkout", "feature") == 0
    assert (repo / "mod.txt").read_text() == "v2"
    assert (repo / "new.txt").read_text() == "brand new"
    assert not (repo / "gone.txt").exists()


def test_checkout_preserves_untracked_files(repo):
    write(repo, "a.txt", "x")
    run("add", ".")
    run("commit", "-m", "c1")
    run("branch", "other")
    write(repo, "untracked.txt", "leave me alone")
    assert run("checkout", "other") == 0
    assert (repo / "untracked.txt").read_text() == "leave me alone"
    assert run("checkout", "main") == 0
    assert (repo / "untracked.txt").read_text() == "leave me alone"


def test_checkout_updates_head_and_branch_pointers(repo):
    write(repo, "a.txt", "x")
    run("add", ".")
    run("commit", "-m", "c1")
    main_sha = head_sha(repo)
    run("branch", "dev")
    run("checkout", "dev")
    assert (repo / ".minigit" / "HEAD").read_text().strip() == \
        "ref: refs/heads/dev"
    write(repo, "a.txt", "y")
    run("add", ".")
    run("commit", "-m", "c2")
    # commit advanced dev, not main
    assert head_sha(repo) != main_sha
    run("checkout", "main")
    assert head_sha(repo) == main_sha


def test_checkout_nonexistent_branch(repo, capsys):
    assert run("checkout", "nope") != 0
    assert "branch not found" in capsys.readouterr().err
