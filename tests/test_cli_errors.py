import os

import pytest

from minigit import cli

from conftest import write


def test_commands_fail_outside_repo(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for argv in (["status"], ["add", "x"], ["commit", "-m", "m"], ["log"],
                 ["branch"], ["checkout", "b"], ["diff"], ["reset", "HEAD"]):
        assert cli.main(argv) != 0, argv
    err = capsys.readouterr().err
    assert "not a minigit repository" in err


def test_unknown_subcommand(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["frobnicate"])
    assert exc.value.code != 0


def test_missing_arguments(capsys):
    for argv in (["add"], ["commit"], ["checkout"], ["reset"]):
        with pytest.raises(SystemExit) as exc:
            cli.main(argv)
        assert exc.value.code != 0, argv


def test_no_command_prints_help(capsys):
    assert cli.main([]) == 2


def test_add_missing_path_errors(repo, run, capsys):
    assert run("add", "does-not-exist.txt") != 0
    assert "did not match" in capsys.readouterr().err


def test_init_creates_structure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    for rel in (".minigit", ".minigit/objects", ".minigit/refs/heads",
                ".minigit/HEAD", ".minigit/index"):
        assert os.path.exists(os.path.join(tmp_path, rel)), rel
    with open(os.path.join(tmp_path, ".minigit", "HEAD")) as fh:
        assert fh.read().strip() == "ref: refs/heads/main"
    # Re-init is idempotent.
    assert cli.main(["init"]) == 0


def test_large_file_add(repo, run):
    # ~4 MB of deterministic pseudo-random data; must not hang or crash.
    chunk = bytes(range(256)) * 4096  # 1 MB
    data = chunk * 4
    write(repo.root, "big.bin", data)
    assert run("add", "big.bin") == 0
    assert run("commit", "-m", "big") == 0
    from minigit import objects, refs
    from minigit.commands import _parse_commit
    _, cdata = objects.read_object(repo, refs.head_commit(repo))
    headers, _ = _parse_commit(cdata)
    flat = objects.flatten_tree(repo, headers["tree"])
    _, blob = objects.read_object(repo, flat["big.bin"][1])
    assert blob == data
