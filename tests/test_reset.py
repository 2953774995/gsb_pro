"""reset --soft / --mixed semantics."""

import os

from conftest import read_file, repo, run_cli, write_file
from minigit import objects as obj
from minigit import refs as refs_mod
from minigit.index import load_index


def _commit_all(message):
    assert run_cli("add", ".")[0] == 0
    code, _, err = run_cli("commit", "-m", message)
    assert code == 0, err


def test_soft_reset_moves_only_branch_pointer(init_repo):
    write_file("a.txt", "v1\n")
    _commit_all("one")
    c1 = refs_mod.head_commit(repo())
    write_file("a.txt", "v2\n")
    _commit_all("two")
    c2 = refs_mod.head_commit(repo())

    code, out, err = run_cli("reset", "--soft", c1)
    assert code == 0, err
    assert refs_mod.head_commit(repo()) == c1
    # index untouched: still the v2 tree -> shows as staged change
    code, short, _ = run_cli("status", "-s")
    assert "M  a.txt" in short
    # working tree untouched
    assert read_file("a.txt") == b"v2\n"


def test_mixed_reset_also_rebuilds_index(init_repo):
    write_file("a.txt", "v1\n")
    _commit_all("one")
    c1 = refs_mod.head_commit(repo())
    write_file("a.txt", "v2\n")
    write_file("b.txt", "new\n")
    _commit_all("two")

    code, _, err = run_cli("reset", "--mixed", c1)
    assert code == 0, err
    assert refs_mod.head_commit(repo()) == c1
    idx = load_index(repo())
    # index now matches c1: a.txt=v1, b.txt absent
    commit = obj.read_commit(repo(), c1)
    head = obj.flatten_tree(repo(), commit["tree"])
    assert dict(idx.entries) == head
    # worktree is left alone: modifications appear as unstaged changes
    assert read_file("a.txt") == b"v2\n"
    code, short, _ = run_cli("status", "-s")
    assert " M a.txt" in short
    assert "?? b.txt" in short


def test_mixed_is_default_mode(init_repo):
    write_file("a", "1")
    _commit_all("c1")
    c1 = refs_mod.head_commit(repo())
    write_file("a", "2")
    _commit_all("c2")
    code, _, err = run_cli("reset", c1)
    assert code == 0, err
    assert refs_mod.head_commit(repo()) == c1


def test_reset_invalid_reference(init_repo):
    write_file("a", "1")
    _commit_all("c")
    code, _, err = run_cli("reset", "--soft", "does-not-exist")
    assert code == 1
    assert "unknown revision" in err
    code, _, err = run_cli("reset", "--soft")
    assert code == 1
    assert "usage" in err
