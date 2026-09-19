import os

from minigit import objects, refs
from minigit.commands import _parse_commit

from conftest import read, write


def commit_file(repo, run, path, content, msg):
    write(repo.root, path, content)
    assert run("add", path) == 0
    assert run("commit", "-m", msg) == 0
    return refs.head_commit(repo)


def test_commit_chain_parent_links(repo, run):
    c1 = commit_file(repo, run, "a.txt", "one", "first")
    c2 = commit_file(repo, run, "b.txt", "two", "second")
    c3 = commit_file(repo, run, "c.txt", "three", "third")

    _, d1 = objects.read_object(repo, c1)
    _, d2 = objects.read_object(repo, c2)
    _, d3 = objects.read_object(repo, c3)
    h1, m1 = _parse_commit(d1)
    h2, m2 = _parse_commit(d2)
    h3, m3 = _parse_commit(d3)

    assert h1["parents"] == []           # root commit has no parent
    assert h2["parents"] == [c1]
    assert h3["parents"] == [c2]
    assert m1.strip() == "first"
    assert "tree" in h1 and "author" in h1


def test_commit_advances_branch(repo, run):
    c1 = commit_file(repo, run, "a.txt", "1", "one")
    assert refs.read_branch(repo, "main") == c1
    c2 = commit_file(repo, run, "a.txt", "2", "two")
    assert refs.read_branch(repo, "main") == c2
    assert c1 != c2


def test_commit_tree_contains_all_staged_files(repo, run):
    write(repo.root, "d/e.txt", "nested")
    write(repo.root, "f.txt", "flat")
    assert run("add", ".") == 0
    assert run("commit", "-m", "snap") == 0
    head = refs.head_commit(repo)
    _, data = objects.read_object(repo, head)
    headers, _ = _parse_commit(data)
    flat = objects.flatten_tree(repo, headers["tree"])
    assert set(flat) == {"d/e.txt", "f.txt"}


def test_log_full_and_oneline(repo, run, capsys):
    c1 = commit_file(repo, run, "a.txt", "1", "first commit")
    c2 = commit_file(repo, run, "a.txt", "2", "second commit\n\nwith body")

    assert run("log") == 0
    out = capsys.readouterr().out
    assert "commit %s" % c2 in out
    assert "commit %s" % c1 in out
    assert out.index(c2) < out.index(c1)  # newest first
    assert "Author:" in out and "Date:" in out
    assert "    second commit" in out

    assert run("log", "--oneline") == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out[0] == "%s second commit" % c2[:7]
    assert out[1] == "%s first commit" % c1[:7]
    assert len(out) == 2


def test_log_without_commits_errors(repo, run, capsys):
    assert run("log") != 0
    assert "does not have any commits" in capsys.readouterr().err


def test_empty_commit_is_rejected(repo, run, capsys):
    commit_file(repo, run, "a.txt", "1", "one")
    head_before = refs.head_commit(repo)
    assert run("commit", "-m", "nothing changed") != 0
    assert "nothing to commit" in capsys.readouterr().err
    assert refs.head_commit(repo) == head_before  # history untouched


def test_commit_without_any_stage_errors(repo, run, capsys):
    assert run("commit", "-m", "x") != 0
    assert "nothing to commit" in capsys.readouterr().err


def test_repeated_add_commit_no_duplicate_blobs(repo, run):
    write(repo.root, "a.txt", "stable content")
    assert run("add", "a.txt") == 0
    assert run("commit", "-m", "one") == 0
    blob_count = sum(len(f) for _, _, f in os.walk(repo.objects_dir))
    # Re-add identical content and commit again -> no new blob objects.
    assert run("add", "a.txt") == 0
    assert run("commit", "-m", "two") != 0  # empty commit rejected
    blob_count_after = sum(len(f) for _, _, f in os.walk(repo.objects_dir))
    assert blob_count_after == blob_count
