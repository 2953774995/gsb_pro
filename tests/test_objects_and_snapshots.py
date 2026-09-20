from __future__ import annotations

import io
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from cfgvault.cli import main
from cfgvault.index import read_index, serialize_index
from cfgvault.objects import (
    hash_blob_bytes,
    iter_object_ids,
    object_id,
    objects_dir,
    read_object,
    write_blob_file,
    write_object,
)
from cfgvault.refs import read_branch
from cfgvault.snapshots import read_snapshot
from cfgvault.trees import IndexEntry, build_tree, parse_tree, read_tree


class Result:
    def __init__(self, code, stdout, stderr):
        self.code = code
        self.stdout = stdout
        self.stderr = stderr


def run_cli(tmp_path: Path, *args: str) -> Result:
    out = io.StringIO()
    err = io.StringIO()
    old = Path.cwd()
    try:
        tmp_path.chdir() if hasattr(Path, "chdir") else None
        import os

        os.chdir(tmp_path)
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args), out=out, err=err)
    finally:
        import os

        os.chdir(old)
    return Result(code, out.getvalue(), err.getvalue())


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_blob_hash_stable_and_deduplicates(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    data = b'{"price": 1999}\n'
    a = root / "a.json"
    b = root / "nested" / "b.json"
    a.write_bytes(data)
    b.parent.mkdir()
    b.write_bytes(data)

    assert hash_blob_bytes(data) == object_id("blob", data)
    oid_a = write_blob_file(root, a)
    oid_b = write_blob_file(root, b)
    assert oid_a == oid_b
    assert len(list(objects_dir(root).glob("*/*"))) == 1
    object_type, payload = read_object(root, oid_a)
    assert object_type == "blob"
    assert payload == data


def test_tree_order_is_deterministic_and_recursive(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    entries = {
        "poster/z.txt": IndexEntry("100644", "z" * 40),
        "prices/a.json": IndexEntry("100644", "a" * 40),
        "prices/b.json": IndexEntry("100644", "b" * 40),
        "poster/a.txt": IndexEntry("100644", "c" * 40),
    }
    first = build_tree(root, dict(entries))
    second = build_tree(root, dict(reversed(list(entries.items()))))
    assert first == second
    flattened = read_tree(root, first)
    assert list(flattened) == sorted(entries)
    root_payload = read_object(root, first)[1]
    root_entries = parse_tree(root_payload)
    assert [(e.mode, e.name) for e in root_entries] == [
        ("40000", "poster"),
        ("40000", "prices"),
    ]


def test_add_snap_log_parent_chain_and_index_reproducibility(tmp_path):
    write(tmp_path / "prices" / "a.json", '{"a": 1}\n')
    write(tmp_path / "poster.txt", "sale\n")
    assert run_cli(tmp_path, "init").code == 0
    assert run_cli(tmp_path, "add", ".").code == 0
    first_index = (tmp_path / ".cfgvault" / "index").read_bytes()
    assert run_cli(tmp_path, "snap", "-m", "first", "--date", "2026-01-01T00:00:00+00:00").code == 0
    assert (tmp_path / ".cfgvault" / "index").read_bytes() == first_index

    write(tmp_path / "prices" / "a.json", '{"a": 2}\n')
    assert run_cli(tmp_path, "add", "prices/a.json").code == 0
    result = run_cli(tmp_path, "snap", "-m", "second", "--date", "2026-01-02T00:00:00+00:00")
    assert result.code == 0
    assert result.code == 0
    second_oid = read_branch(tmp_path, "main")

    log = run_cli(tmp_path, "log", "--oneline")
    lines = [line for line in log.stdout.splitlines() if line]
    assert lines[0].endswith("second")
    assert lines[1].endswith("first")
    second = read_snapshot(tmp_path, second_oid)
    assert second["message"] == "second"
    assert second["parent"] is not None
    parent = read_snapshot(tmp_path, second["parent"])
    assert parent["message"] == "first"
    assert parent["parent"] is None

    entries = read_index(tmp_path)
    assert serialize_index(entries) == (tmp_path / ".cfgvault" / "index").read_bytes()


def test_branch_checkout_restores_add_overwrite_and_delete(tmp_path):
    write(tmp_path / "common.json", '{"v": "main"}\n')
    write(tmp_path / "only-main.json", "main only\n")
    assert run_cli(tmp_path, "init").code == 0
    assert run_cli(tmp_path, "add", ".").code == 0
    assert run_cli(tmp_path, "snap", "-m", "main").code == 0

    assert run_cli(tmp_path, "branch", "promo").code == 0
    branches = run_cli(tmp_path, "branch")
    assert "* main" in branches.stdout
    assert "  promo" in branches.stdout
    assert run_cli(tmp_path, "checkout", "promo").code == 0

    # Overwrite, add, and delete.
    write(tmp_path / "common.json", '{"v": "promo"}\n')
    write(tmp_path / "only-promo.json", "promo only\n")
    assert run_cli(tmp_path, "add", "common.json").code == 0
    assert run_cli(tmp_path, "add", "only-promo.json").code == 0
    assert run_cli(tmp_path, "add", "only-main.json").code == 0  # missing tracked path stages deletion
    assert run_cli(tmp_path, "snap", "-m", "promo").code == 0

    # Untracked files survive checkout.
    write(tmp_path / "untracked.txt", "keep me\n")
    assert run_cli(tmp_path, "checkout", "main").code == 0
    assert (tmp_path / "common.json").read_text() == '{"v": "main"}\n'
    assert (tmp_path / "only-main.json").exists()
    assert not (tmp_path / "only-promo.json").exists()
    assert (tmp_path / "untracked.txt").read_text() == "keep me\n"


def test_empty_snap_is_noop_until_allow_empty(tmp_path):
    write(tmp_path / "a.json", "{}\n")
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "add", ".")
    first = run_cli(tmp_path, "snap", "-m", "first")
    assert first.code == 0
    before = set(iter_object_ids(tmp_path))
    result = run_cli(tmp_path, "snap", "-m", "second")
    assert result.code == 0
    assert "not created" in result.stdout
    assert set(iter_object_ids(tmp_path)) == before

    allowed = run_cli(tmp_path, "snap", "-m", "empty marker", "--allow-empty")
    assert allowed.code == 0
    lines = [line for line in run_cli(tmp_path, "log", "--oneline").stdout.splitlines() if line]
    assert [line.split(" ", 1)[1] for line in lines] == ["empty marker", "first"]


def test_large_file_add_is_streamed_and_restorable(tmp_path):
    run_cli(tmp_path, "init")
    large = tmp_path / "large.json"
    payload = (b'{"line": ' + b"x" * 256 + b"}\n") * 20000
    assert len(payload) > 4 * 1024 * 1024
    large.write_bytes(payload)
    start = time.monotonic()
    result = run_cli(tmp_path, "add", "large.json")
    elapsed = time.monotonic() - start
    assert result.code == 0
    assert elapsed < 10
    run_cli(tmp_path, "snap", "-m", "large")
    run_cli(tmp_path, "branch", "copy")
    run_cli(tmp_path, "checkout", "copy")
    assert (tmp_path / "large.json").read_bytes() == payload


def test_repeated_add_and_snap_does_not_create_duplicate_blob(tmp_path):
    write(tmp_path / "same.json", '{"same": true}\n')
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "add", "same.json")
    run_cli(tmp_path, "snap", "-m", "one")
    run_cli(tmp_path, "add", "same.json")
    run_cli(tmp_path, "snap", "-m", "two", "--allow-empty")
    blob_oid = hash_blob_bytes(b'{"same": true}\n')
    assert (tmp_path / ".cfgvault" / "objects" / blob_oid[:2] / blob_oid[2:]).is_file()
    assert len(list((tmp_path / ".cfgvault" / "objects").glob("*/*"))) >= 3
