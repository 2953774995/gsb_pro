from __future__ import annotations

import re
from pathlib import Path

from cfgvault.index import read_index
from cfgvault.objects import read_snapshot
from cfgvault.refs import read_head_oid
from cfgvault.repo import find_repository
from conftest import write


def oid(result):
    match = re.search(r"\b[0-9a-f]{40}\b", result.stdout)
    assert match, result.stdout
    return match.group(0)


def prepare_history(run_cli):
    run_cli("init")
    write("f.txt", "version1\n")
    run_cli("add", ".")
    first = oid(run_cli("snap", "-m", "v1"))
    write("f.txt", "version2\n")
    run_cli("add", ".")
    second = oid(run_cli("snap", "-m", "v2"))
    return first, second


def test_reset_soft_moves_ref_but_leaves_worktree_and_index(run_cli):
    first, second = prepare_history(run_cli)
    write("f.txt", "worktree3\n")

    assert run_cli("reset", "--soft", first).code == 0
    repo = find_repository()
    assert read_head_oid(repo) == first
    assert read_snapshot(repo, first).parent is None
    index = read_index(repo)
    from cfgvault.objects import flatten_tree
    assert index.get("f.txt").oid == flatten_tree(repo, read_snapshot(repo, second).tree)["f.txt"][1]
    assert Path("f.txt").read_text() == "worktree3\n"


def test_reset_mixed_moves_ref_and_rebuilds_index_but_not_worktree(run_cli):
    first, second = prepare_history(run_cli)
    write("f.txt", "worktree3\n")

    assert run_cli("reset", "--mixed", first).code == 0
    repo = find_repository()
    assert read_head_oid(repo) == first
    index_blob = read_index(repo).get("f.txt").oid
    snapshot = read_snapshot(repo, first)
    from cfgvault.objects import flatten_tree

    assert index_blob == flatten_tree(repo, snapshot.tree)["f.txt"][1]
    assert Path("f.txt").read_text() == "worktree3\n"
    status = run_cli("status", "--short").stdout
    assert " M f.txt" in status


def test_invalid_snapshot_and_missing_branch_produce_nonzero(run_cli):
    prepare_history(run_cli)
    result = run_cli("reset", "--soft", "deadbeef")
    assert result.code != 0
    assert "snapshot not found" in result.stderr

    result = run_cli("checkout", "missing")
    assert result.code != 0
    assert "branch does not exist" in result.stderr


def test_commands_outside_repository_fail_clearly(run_cli, tmp_path):
    # run_cli already chdirs into an empty temporary directory.
    for argv in (("status",), ("add", "x"), ("snap", "-m", "x"), ("log",), ("branch",)):
        result = run_cli(*argv)
        assert result.code != 0
        assert "not a cfgvault repository" in result.stderr


def test_missing_arguments_fail_nonzero(run_cli):
    run_cli("init")
    assert run_cli("add").code != 0
    assert run_cli("checkout").code != 0
    assert run_cli("reset", "--soft").code != 0


def test_large_file_add_snap_status_is_responsive(run_cli):
    run_cli("init")
    large = Path("large.json")
    with large.open("wb") as stream:
        for i in range(80):
            stream.write((b"x" * 64 * 1024) + bytes([i % 256]))
    start = __import__("time").monotonic()
    assert run_cli("add", "large.json").code == 0
    assert run_cli("snap", "-m", "large").code == 0
    status = run_cli("status", "--short")
    assert status.code == 0
    assert "large.json" not in status.stdout
    assert __import__("time").monotonic() - start < 15
