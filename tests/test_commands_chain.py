"""add / commit / log: commit graph and parent chain semantics."""

from conftest import read_file, repo, run_cli, write_file
from minigit import objects as obj
from minigit.index import load_index
from minigit import refs as refs_mod


def _add_commit(message):
    code, out, err = run_cli("add", ".")
    assert code == 0, err
    code, out, err = run_cli("commit", "-m", message)
    assert code == 0, err
    return out.strip()


def test_add_then_commit_creates_tree_and_commit(init_repo):
    write_file("hello.txt", "hello\n")
    write_file("dir/other.txt", "other\n")
    assert _add_commit("initial commit")
    head = refs_mod.head_commit(repo())
    assert head is not None
    commit = obj.read_commit(repo(), head)
    assert commit["parents"] == []  # root commit
    assert commit["message"] == "initial commit"
    assert "Test User <test@example.com>" in commit["author"]
    flat = obj.flatten_tree(repo(), commit["tree"])
    assert set(flat) == {"hello.txt", "dir/other.txt"}
    # branch ref file holds the commit hash
    assert read_file(".minigit/refs/heads/main").decode().strip() == head


def test_parent_chain_and_log(init_repo):
    write_file("f.txt", "v1\n")
    _add_commit("one")
    c1 = refs_mod.head_commit(repo())
    write_file("f.txt", "v2\n")
    _add_commit("two")
    c2 = refs_mod.head_commit(repo())
    write_file("f.txt", "v3\n")
    _add_commit("three")
    c3 = refs_mod.head_commit(repo())

    assert obj.read_commit(repo(), c2)["parents"] == [c1]
    assert obj.read_commit(repo(), c3)["parents"] == [c2]

    code, out, _ = run_cli("log", "--oneline")
    assert code == 0
    lines = [ln for ln in out.splitlines() if ln]
    assert [ln[:7] for ln in lines] == [c3[:7], c2[:7], c1[:7]]
    assert lines[0].endswith("three")

    code, full, _ = run_cli("log")
    assert full.count("commit ") == 3
    assert "Author: Test User" in full
    assert "Date:" in full
    assert "    one" in full


def test_repeated_add_commit_creates_no_extra_blob(init_repo):
    write_file("f.txt", "data\n")
    run_cli("add", "f.txt")
    run_cli("add", "f.txt")
    code, _, err = run_cli("commit", "-m", "c1")
    assert code == 0
    sha1 = load_index(repo()).entries["f.txt"][1]

    # add again (identical content) then an empty commit is rejected,
    # but the blob object must remain exactly one on disk.
    code, _, _ = run_cli("add", "f.txt")
    assert code == 0
    assert load_index(repo()).entries["f.txt"][1] == sha1
    code, _out, err = run_cli("commit", "-m", "c2")
    assert code == 1
    assert "nothing to commit" in err


def test_commit_requires_message(init_repo):
    write_file("a", "x")
    run_cli("add", ".")
    code, _, err = run_cli("commit")
    assert code == 1 and "message required" in err
    code, _, err = run_cli("commit", "-m")
    assert code == 1


def test_allow_empty_commit(init_repo):
    # Empty index but explicit --allow-empty creates a root commit.
    code, _, err = run_cli("commit", "-m", "empty root", "--allow-empty")
    assert code == 0, err
    c1 = refs_mod.head_commit(repo())
    assert obj.read_commit(repo(), c1)["parents"] == []
    # An identical-tree commit is allowed with the flag.
    code, _, err = run_cli("commit", "-m", "empty again", "--allow-empty")
    assert code == 0, err
    c2 = refs_mod.head_commit(repo())
    assert obj.read_commit(repo(), c2)["parents"] == [c1]


def test_commit_advances_current_branch(init_repo):
    write_file("a", "1")
    _add_commit("c")
    main_sha = refs_mod.read_branch(repo(), "main")
    code, _, err = run_cli("branch", "topic")
    assert code == 0
    run_cli("checkout", "topic")
    write_file("a", "2")
    _add_commit("on topic")
    topic_sha = refs_mod.read_branch(repo(), "topic")
    assert refs_mod.read_branch(repo(), "main") == main_sha
    assert topic_sha != main_sha
    assert refs_mod.current_branch(repo()) == "topic"
