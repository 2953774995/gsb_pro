"""add / commit / log: commit chain integrity and log output."""

from conftest import head_sha, run, write

from minigit.objects import ObjectStore, parse_commit


def _commit(repo, sha):
    store = ObjectStore(str(repo / ".minigit"))
    obj_type, data = store.read_object(sha)
    assert obj_type == "commit"
    return parse_commit(data)


def test_commit_chain_parent_links(repo):
    write(repo, "a.txt", "one")
    assert run("add", ".") == 0
    assert run("commit", "-m", "first commit") == 0
    first = head_sha(repo)

    write(repo, "a.txt", "two")
    assert run("add", ".") == 0
    assert run("commit", "-m", "second commit") == 0
    second = head_sha(repo)

    assert first != second
    c2 = _commit(repo, second)
    assert c2["parents"] == [first]
    assert c2["message"].strip() == "second commit"
    c1 = _commit(repo, first)
    assert c1["parents"] == []
    assert c1["message"].strip() == "first commit"


def test_log_full_output(repo, capsys):
    write(repo, "a.txt", "v1")
    run("add", ".")
    run("commit", "-m", "initial commit")
    write(repo, "a.txt", "v2")
    run("add", ".")
    run("commit", "-m", "update a")
    second = head_sha(repo)

    capsys.readouterr()
    assert run("log") == 0
    out = capsys.readouterr().out
    assert "commit %s" % second in out
    assert "Author:" in out
    assert "Date:" in out
    assert "    update a" in out
    assert "    initial commit" in out
    # newest first
    assert out.index("update a") < out.index("initial commit")


def test_log_oneline(repo, capsys):
    write(repo, "a.txt", "v1")
    run("add", ".")
    run("commit", "-m", "first line\n\nbody ignored in oneline")
    sha = head_sha(repo)

    capsys.readouterr()
    assert run("log", "--oneline") == 0
    out = capsys.readouterr().out.strip()
    assert out == "%s first line" % sha[:7]


def test_empty_commit_rejected(repo, capsys):
    write(repo, "a.txt", "x")
    run("add", ".")
    assert run("commit", "-m", "c1") == 0
    before = head_sha(repo)
    capsys.readouterr()
    assert run("commit", "-m", "c2") != 0  # nothing staged
    out = capsys.readouterr().out
    assert "nothing to commit" in out
    assert head_sha(repo) == before  # branch pointer unchanged


def test_commit_with_empty_index_rejected(repo, capsys):
    capsys.readouterr()
    assert run("commit", "-m", "nothing") != 0
    assert "nothing to commit" in capsys.readouterr().out


def test_commit_advances_current_branch_only(repo):
    write(repo, "a.txt", "x")
    run("add", ".")
    run("commit", "-m", "on main")
    run("branch", "feature")
    run("checkout", "feature")
    write(repo, "b.txt", "y")
    run("add", ".")
    run("commit", "-m", "on feature")
    main_ref = (repo / ".minigit" / "refs" / "heads" / "main").read_text().strip()
    feat_ref = (repo / ".minigit" / "refs" / "heads" / "feature").read_text().strip()
    assert main_ref != feat_ref
    assert head_sha(repo) == feat_ref
