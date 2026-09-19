import os

from minigit import refs
from minigit.index import read_index

from conftest import read, write


def make_history(repo, run):
    write(repo.root, "a.txt", "v1")
    run("add", ".")
    run("commit", "-m", "c1")
    c1 = refs.head_commit(repo)
    write(repo.root, "a.txt", "v2")
    run("add", ".")
    run("commit", "-m", "c2")
    c2 = refs.head_commit(repo)
    write(repo.root, "a.txt", "v3")
    run("add", ".")
    run("commit", "-m", "c3")
    c3 = refs.head_commit(repo)
    return c1, c2, c3


def test_reset_soft_moves_pointer_only(repo, run):
    c1, c2, c3 = make_history(repo, run)
    index_before = dict(read_index(repo))
    write(repo.root, "dirty.txt", "untouched")
    assert run("reset", "--soft", c1) == 0
    assert refs.head_commit(repo) == c1
    # Index and worktree are untouched.
    assert dict(read_index(repo)) == index_before
    assert read(repo.root, "a.txt") == "v3"
    assert read(repo.root, "dirty.txt") == "untouched"


def test_reset_mixed_resets_index(repo, run):
    c1, c2, c3 = make_history(repo, run)
    assert run("reset", "--mixed", c1) == 0
    assert refs.head_commit(repo) == c1
    entries = read_index(repo)
    # Index now matches c1's tree...
    from minigit import objects
    assert "a.txt" in entries
    head_flat = {}
    from minigit.commands import _parse_commit
    _, data = objects.read_object(repo, c1)
    headers, _ = _parse_commit(data)
    head_flat = objects.flatten_tree(repo, headers["tree"])
    assert entries["a.txt"].oid == head_flat["a.txt"][1]
    # ...but the worktree still has v3.
    assert read(repo.root, "a.txt") == "v3"


def test_reset_accepts_branch_and_short_hash(repo, run):
    c1, c2, c3 = make_history(repo, run)
    run("branch", "topic")  # at c3
    assert run("reset", "--soft", c1[:8]) == 0
    assert refs.head_commit(repo) == c1
    assert run("reset", "--soft", "topic") == 0
    assert refs.head_commit(repo) == c3


def test_reset_invalid_commit_errors(repo, run, capsys):
    make_history(repo, run)
    assert run("reset", "--soft", "deadbeefdeadbeef") != 0
    assert "invalid commit reference" in capsys.readouterr().err
    assert run("reset", "--mixed", "no-such-branch") != 0
    assert "invalid commit reference" in capsys.readouterr().err
