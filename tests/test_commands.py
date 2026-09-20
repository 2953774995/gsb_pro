from __future__ import annotations

import os
import re
import time
from pathlib import Path


from cfgvault.index import read_index
from cfgvault.objects import read_snapshot
from cfgvault.refs import read_head_oid
from cfgvault.repo import find_repository
from conftest import write

HASH_RE = re.compile(r"\b[0-9a-f]{40}\b")
SHORT_RE = re.compile(r"\b[0-9a-f]{8}\b")


def oid_from(result):
    match = HASH_RE.search(result.stdout)
    assert match, result.stdout
    return match.group(0)


def test_init_add_snap_log_and_parent_chain(run_cli):
    assert run_cli("init").code == 0
    write("prices/a.json", "a\n")
    write("poster/b.txt", "b\n")

    assert run_cli("add", "prices", "poster").code == 0
    result = run_cli("snap", "-m", "daily version")
    assert result.code == 0
    first = oid_from(result)

    result = run_cli("snap", "-m", "repeat snapshot")
    assert result.code == 0
    second = oid_from(result)
    assert second != first

    repo = find_repository()
    assert read_snapshot(repo, second).parent == first
    assert read_snapshot(repo, first).parent is None
    assert read_snapshot(repo, second).tree == read_snapshot(repo, first).tree

    log = run_cli("log").stdout
    assert second in log and first in log
    assert log.index(second) < log.index(first)
    assert "Operator <ops@example.com>" in log
    assert "daily version" in log

    oneline = run_cli("log", "--oneline").stdout.splitlines()
    assert SHORT_RE.fullmatch(oneline[0].split(" ", 1)[0])
    assert oneline[0].endswith("repeat snapshot")
    assert oneline[1].endswith("daily version")


def test_repeated_add_and_snap_reuses_blobs(run_cli):
    run_cli("init")
    write("f.json", "same\n")
    run_cli("add", "f.json")
    first_snap = oid_from(run_cli("snap", "-m", "one"))
    run_cli("add", "f.json")
    second_snap = oid_from(run_cli("snap", "-m", "two"))

    repo = find_repository()
    assert read_snapshot(repo, first_snap).tree == read_snapshot(repo, second_snap).tree
    assert read_snapshot(repo, second_snap).parent == first_snap

    blob_ids = []
    for base, _, files in os.walk(repo.objects_dir):
        for filename in files:
            path = Path(base) / filename
            oid = path.parent.name + filename
            blob_ids.append(oid)
    # One blob, one tree (deduplicated), two snapshots = four objects.
    assert len(blob_ids) == 4


def test_branch_checkout_adds_overwrites_deletes_and_preserves_untracked(run_cli):
    run_cli("init")
    write("shared.txt", "daily shared\n")
    write("daily_only.txt", "daily\n")
    write("price/f.json", "daily price\n")
    run_cli("add", ".")
    run_cli("snap", "-m", "daily")

    assert run_cli("branch", "promo").code == 0
    assert run_cli("checkout", "promo").code == 0
    write("promo_only.txt", "promo\n")
    write("price/f.json", "promo price\n")
    os.unlink("daily_only.txt")
    run_cli("add", ".")
    run_cli("snap", "-m", "promo")
    write("untracked.txt", "keep me\n")
    assert run_cli("checkout", "main").code == 0

    branches = run_cli("branch").stdout.splitlines()
    assert "* main" in branches
    assert "  promo" in branches

    assert Path("daily_only.txt").read_text() == "daily\n"
    assert Path("price/f.json").read_text() == "daily price\n"
    assert not Path("promo_only.txt").exists()
    assert Path("untracked.txt").read_text() == "keep me\n"
    assert run_cli("status", "--short").stdout == "## main\n?? untracked.txt\n\n"

    assert run_cli("checkout", "promo").code == 0
    assert Path("promo_only.txt").read_text() == "promo\n"
    assert Path("price/f.json").read_text() == "promo price\n"
    assert not Path("daily_only.txt").exists()
    assert Path("untracked.txt").exists()


def test_branch_creation_advances_current_branch_after_snap(run_cli):
    run_cli("init")
    write("a", "a")
    run_cli("add", ".")
    daily = oid_from(run_cli("snap", "-m", "daily"))
    run_cli("branch", "promo")
    write("a", "b")
    run_cli("add", ".")
    promo = oid_from(run_cli("snap", "-m", "promo"))

    assert read_head_oid(find_repository()) == promo
    assert run_cli("checkout", "promo").code == 0
    # promo was created before the second snap and still points to daily.
    assert read_head_oid(find_repository()) == daily


def test_empty_snapshot_is_allowed_and_points_at_empty_tree(run_cli):
    run_cli("init")
    result = run_cli("snap", "-m", "empty baseline")
    assert result.code == 0
    oid = oid_from(result)
    snapshot = read_snapshot(find_repository(), oid)
    assert snapshot.parent is None
    assert snapshot.tree == "d28c5ff92df044a522508a29cf3fad0b812f672f"
    assert run_cli("log", "--oneline").stdout.strip().endswith("empty baseline")


def test_snap_requires_message_and_unknown_command_fails(run_cli):
    run_cli("init")
    result = run_cli("snap")
    assert result.code != 0
    assert "message" in result.stderr
    result = run_cli("frobnicate")
    assert result.code != 0
