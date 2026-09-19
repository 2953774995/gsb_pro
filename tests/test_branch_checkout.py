import os

from minigit import refs

from conftest import read, write


def setup_two_branches(repo, run):
    """main: shared.txt='main version', only_main.txt; feature: shared.txt
    overwritten, only_feature.txt added, only_main.txt untouched."""
    write(repo.root, "shared.txt", "main version")
    write(repo.root, "only_main.txt", "main only")
    assert run("add", ".") == 0
    assert run("commit", "-m", "main commit") == 0

    assert run("branch", "feature") == 0
    assert run("checkout", "feature") == 0
    write(repo.root, "shared.txt", "feature version")   # overwrite case
    write(repo.root, "only_feature.txt", "feature only")  # added case
    os.remove(os.path.join(repo.root, "only_main.txt"))   # deleted case
    assert run("add", ".") == 0
    # Stage the deletion explicitly via index rebuild: add won't remove files,
    # so emulate git's behaviour by committing the remaining tree.
    from minigit import index as indexmod
    entries = indexmod.read_index(repo)
    del entries["only_main.txt"]
    indexmod.write_index(repo, entries)
    assert run("commit", "-m", "feature commit") == 0


def test_branch_create_and_list(repo, run, capsys):
    write(repo.root, "a.txt", "x")
    run("add", ".")
    run("commit", "-m", "c1")
    assert run("branch", "dev") == 0
    assert run("branch") == 0
    out = capsys.readouterr().out.splitlines()
    assert "* main" in out
    assert "  dev" in out
    # Branch points at the same commit as HEAD.
    assert refs.read_branch(repo, "dev") == refs.head_commit(repo)


def test_branch_duplicate_errors(repo, run, capsys):
    write(repo.root, "a.txt", "x")
    run("add", ".")
    run("commit", "-m", "c1")
    run("branch", "dev")
    assert run("branch", "dev") != 0
    assert "already exists" in capsys.readouterr().err


def test_branch_without_commits_errors(repo, run, capsys):
    assert run("branch", "dev") != 0
    assert "no commits" in capsys.readouterr().err


def test_checkout_restores_worktree(repo, run):
    setup_two_branches(repo, run)
    # On feature: verify state.
    assert read(repo.root, "shared.txt") == "feature version"
    assert os.path.exists(os.path.join(repo.root, "only_feature.txt"))
    assert not os.path.exists(os.path.join(repo.root, "only_main.txt"))

    assert run("checkout", "main") == 0
    # overwritten file restored
    assert read(repo.root, "shared.txt") == "main version"
    # file added on feature is removed (it was tracked there)
    assert not os.path.exists(os.path.join(repo.root, "only_feature.txt"))
    # file deleted on feature is restored
    assert read(repo.root, "only_main.txt") == "main only"

    assert run("checkout", "feature") == 0
    assert read(repo.root, "shared.txt") == "feature version"
    assert read(repo.root, "only_feature.txt") == "feature only"
    assert not os.path.exists(os.path.join(repo.root, "only_main.txt"))


def test_checkout_keeps_untracked_files(repo, run):
    setup_two_branches(repo, run)
    write(repo.root, "untracked.txt", "keep me")
    assert run("checkout", "main") == 0
    assert read(repo.root, "untracked.txt") == "keep me"
    assert run("checkout", "feature") == 0
    assert read(repo.root, "untracked.txt") == "keep me"


def test_checkout_unknown_branch_errors(repo, run, capsys):
    write(repo.root, "a.txt", "x")
    run("add", ".")
    run("commit", "-m", "c1")
    assert run("checkout", "nope") != 0
    assert "nope" in capsys.readouterr().err


def test_checkout_updates_head(repo, run):
    setup_two_branches(repo, run)
    assert refs.current_branch(repo) == "feature"
    run("checkout", "main")
    assert refs.current_branch(repo) == "main"
