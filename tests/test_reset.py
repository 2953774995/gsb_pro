"""reset --soft / --mixed semantics and invalid references."""

from conftest import head_sha, run, write


def _two_commits(repo):
    write(repo, "a.txt", "v1")
    run("add", ".")
    run("commit", "-m", "c1")
    first = head_sha(repo)
    write(repo, "a.txt", "v2")
    run("add", ".")
    run("commit", "-m", "c2")
    return first, head_sha(repo)


def test_reset_soft_moves_pointer_keeps_index(repo, capsys):
    first, second = _two_commits(repo)
    assert first != second
    assert run("reset", "--soft", first) == 0
    assert head_sha(repo) == first
    # index still holds v2 -> staged modification relative to new HEAD
    capsys.readouterr()
    assert run("status", "--short") == 0
    assert "M  a.txt" in capsys.readouterr().out.splitlines()
    # working tree untouched
    assert (repo / "a.txt").read_text() == "v2"


def test_reset_mixed_resets_index(repo, capsys):
    first, second = _two_commits(repo)
    assert run("reset", "--mixed", first) == 0
    assert head_sha(repo) == first
    # index now matches first commit; v2 content only in the working tree
    capsys.readouterr()
    assert run("status", "--short") == 0
    assert " M a.txt" in capsys.readouterr().out.splitlines()
    assert (repo / "a.txt").read_text() == "v2"


def test_reset_accepts_branch_name_and_prefix(repo):
    first, second = _two_commits(repo)
    run("branch", "keep")
    assert run("reset", "--soft", "keep") == 0
    assert head_sha(repo) == second  # keep points at c2
    assert run("reset", "--soft", first[:8]) == 0  # abbreviated sha
    assert head_sha(repo) == first


def test_reset_invalid_commit(repo, capsys):
    _two_commits(repo)
    assert run("reset", "--soft", "deadbeefdeadbeef") != 0
    assert "invalid commit reference" in capsys.readouterr().err
    assert run("reset", "--mixed", "no-such-branch") != 0
    assert "invalid commit reference" in capsys.readouterr().err
