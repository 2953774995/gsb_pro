"""Error handling edge cases and the binary index format."""

import os

from conftest import repo, run_cli, write_file
from minigit.errors import NotARepositoryError
from minigit.index import Index, load_index
from minigit.repository import Repository


def test_commands_outside_repository(repo_dir):
    for argv in (
        ["status"], ["add", "."], ["commit", "-m", "x"], ["log"],
        ["branch"], ["checkout", "x"], ["diff"], ["reset", "HEAD"],
    ):
        code, out, err = run_cli(*argv)
        assert code == 1, argv
        assert "not a minigit repository" in err, argv


def test_unknown_command_and_help(init_repo):
    code, _, err = run_cli("frobnicate")
    assert code == 1 and "not a minigit command" in err
    code, out, _ = run_cli("--help")
    assert code == 0 and "minigit <command>" in out
    code, out, _ = run_cli()
    assert code == 0


def test_missing_arguments(init_repo):
    assert run_cli("add")[0] == 1
    assert run_cli("checkout")[0] == 1
    assert run_cli("reset")[0] == 1


def test_log_unknown_revision(init_repo):
    code, _, err = run_cli("log", "nope")
    assert code == 1 and "unknown revision" in err


def test_add_nonexistent_path(init_repo):
    code, _, err = run_cli("add", "missing.txt")
    assert code == 1 and "did not match" in err


def test_index_roundtrip_and_stable_bytes(init_repo):
    entries = {
        "z.txt": (0o100644, "a" * 40),
        "a.txt": (0o100755, "b" * 40),
        "d/m.txt": (0o100644, "c" * 40),
    }
    idx = Index(entries)
    raw = idx.to_bytes()
    assert raw[:4] == b"MIDX"
    again = Index(entries).to_bytes()
    assert raw == again  # deterministic
    rebuilt = Index.from_bytes(raw)
    assert rebuilt.entries == entries
    # Ordering inside the file is by path: a.txt precedes z.txt.
    assert raw.index(b"a.txt") < raw.index(b"z.txt")
    # Empty index serialises/parses too.
    assert Index.from_bytes(Index().to_bytes()).entries == {}


def test_missing_index_loads_empty(init_repo):
    assert load_index(repo()).entries == {}


def test_init_is_idempotent(init_repo, repo_dir):
    head_before = open(".minigit/HEAD").read()
    assert run_cli("init")[0] == 0
    assert open(".minigit/HEAD").read() == head_before
