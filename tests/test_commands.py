from pathlib import Path

import pytest

from minigit import index as index_mod
from minigit import objects, refs
from minigit.cli import main
from minigit.commits import read_commit
from minigit.repository import Repository


def run(*args, expect=0):
    code = main(list(args))
    assert code == expect
    return code


def write(name, content):
    path = Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def commit_tree(files, message):
    root = Path.cwd()
    for tracked in _all_tracked_files(root):
        tracked.unlink()
    for name, content in files.items():
        write(name, content)
    run("add", ".")
    run("commit", "-m", message)


def _all_tracked_files(root):
    from minigit import index as index_module
    from minigit.repository import Repository
    index_path = Repository(root).index_file
    if not index_path.exists():
        return []
    return [root / path for path in index_module.read_index(index_path)]


def test_add_commit_log_parent_chain(repo, capsys):
    commit_tree({"a.txt": "one\n"}, "first")
    first = refs.head_commit(Repository(repo))
    assert first is not None
    assert (repo / ".minigit" / "refs" / "heads" / "main").read_text().strip() == first
    first_commit = read_commit(repo / ".minigit" / "objects", first)
    assert first_commit.parents == []
    assert "first" in first_commit.message

    commit_tree({"a.txt": "two\n", "b.txt": "second\n"}, "second")
    second = refs.head_commit(Repository(repo))
    second_commit = read_commit(repo / ".minigit" / "objects", second)
    assert second_commit.parents == [first]
    assert objects.read_tree_flat(repo / ".minigit" / "objects", second_commit.tree)["a.txt"][1] != objects.read_tree_flat(
        repo / ".minigit" / "objects", first_commit.tree
    )["a.txt"][1]

    run("log")
    output = capsys.readouterr().out
    assert second in output
    assert first in output
    assert "Author: Test User <test@example.com>" in output
    assert "first" in output and "second" in output
    assert output.index(second) < output.index(first)

    run("log", "--oneline")
    oneline = capsys.readouterr().out.splitlines()
    assert oneline == [f"{second[:7]} second", f"{first[:7]} first"]


def test_branch_creation_listing_and_advances_current_branch(repo, capsys):
    commit_tree({"f": "v1\n"}, "base")
    base = refs.head_commit(Repository(repo))
    run("branch", "feature")
    run("branch")
    assert "* main" in capsys.readouterr().out
    assert (repo / ".minigit" / "refs" / "heads" / "feature").read_text().strip() == base

    write("f", "v2\n")
    run("add", "f")
    run("commit", "-m", "main advance")
    assert refs.read_branch(Repository(repo), "feature") == base
    assert refs.head_commit(Repository(repo)) != base


def test_checkout_restores_added_overwritten_and_deleted_files(repo, capsys):
    commit_tree({"keep.txt": "same\n", "change.txt": "old\n", "remove.txt": "gone\n"}, "base")
    run("branch", "old")
    commit_tree({"keep.txt": "same\n", "change.txt": "new\n", "added.txt": "added\n"}, "newer")

    # Untracked file must survive both checkouts.
    Path("untracked.txt").write_text("survive\n")
    run("checkout", "old")
    assert Path("change.txt").read_text() == "old\n"
    assert not Path("remove.txt").exists() is False
    assert Path("remove.txt").read_text() == "gone\n"
    assert not Path("added.txt").exists()
    assert Path("untracked.txt").read_text() == "survive\n"
    run("branch")
    assert "* old" in capsys.readouterr().out

    run("checkout", "main")
    assert Path("change.txt").read_text() == "new\n"
    assert Path("added.txt").read_text() == "added\n"
    assert not Path("remove.txt").exists()
    assert Path("untracked.txt").read_text() == "survive\n"
    assert index_mod.read_index(Repository(repo).index_file) == objects.read_tree_flat(
        Repository(repo).objects_dir, read_commit(Repository(repo).objects_dir, refs.head_commit(Repository(repo))).tree
    )


def test_repeated_identical_commit_does_not_create_duplicate_blob(repo, capsys):
    write("same.txt", "do not duplicate\n")
    run("add", "same.txt")
    first_index = index_mod.read_index(Repository(repo).index_file)
    run("commit", "-m", "first")
    run("add", "same.txt")
    run("commit", "-m", "no changes", expect=1)
    assert "nothing to commit" in capsys.readouterr().out
    assert index_mod.read_index(Repository(repo).index_file) == first_index
    run("commit", "-m", "explicit empty", "--allow-empty")
    history = capsys.readouterr().out
    assert "explicit empty" in history


def test_empty_initial_commit_is_rejected_consistently(repo, capsys):
    run("commit", "-m", "empty", expect=1)
    out = capsys.readouterr().out
    assert "nothing to commit" in out
    assert not (repo / ".minigit" / "refs" / "heads" / "main").exists()


def test_checkout_unknown_branch_and_duplicate_branch_errors(repo, capsys):
    commit_tree({"f": "x\n"}, "x")
    run("checkout", "missing", expect=1)
    assert "branch does not exist: missing" in capsys.readouterr().err
    run("branch", "nope")
    run("branch", "nope", expect=1)
    assert "branch already exists" in capsys.readouterr().err


def test_reset_soft_and_mixed_semantics(repo, capsys):
    commit_tree({"a.txt": "first\n"}, "first")
    first = refs.head_commit(Repository(repo))
    commit_tree({"a.txt": "second\n", "b.txt": "new\n"}, "second")
    second = refs.head_commit(Repository(repo))
    _, second_tree = _head_tree(repo)

    run("reset", "--soft", first)
    assert refs.head_commit(Repository(repo)) == first
    assert Path("a.txt").read_text() == "second\n"
    assert Path("b.txt").read_text() == "new\n"
    assert index_mod.read_index(Repository(repo).index_file) == second_tree
    run("status", "--short")
    staged = capsys.readouterr().out
    assert "M  a.txt" in staged and "A  b.txt" in staged

    run("reset", "--mixed", second)
    run("reset", "--mixed", first)
    assert refs.head_commit(Repository(repo)) == first
    _, first_tree = _head_tree(repo)
    assert index_mod.read_index(Repository(repo).index_file) == first_tree
    assert Path("a.txt").read_text() == "second\n"
    assert Path("b.txt").read_text() == "new\n"
    run("status", "--short")
    mixed_status = capsys.readouterr().out
    assert " M a.txt" in mixed_status and "? b.txt" in mixed_status
    run("reset", "--soft", "deadbeef", expect=1)
    assert "unknown commit reference" in capsys.readouterr().err


def _head_tree(root):
    repo = Repository(root)
    commit_hash = refs.head_commit(repo)
    commit = read_commit(repo.objects_dir, commit_hash)
    return commit_hash, objects.read_tree_flat(repo.objects_dir, commit.tree)
