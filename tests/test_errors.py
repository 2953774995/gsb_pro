"""Error handling: exit codes and messages for misuse."""

from conftest import run


def test_commands_outside_repo_fail(workdir, capsys):
    for argv in (["status"], ["log"], ["add", "x.txt"],
                 ["commit", "-m", "m"], ["branch"], ["diff"]):
        assert run(*argv) != 0
        assert "not a minigit repository" in capsys.readouterr().err


def test_unknown_command(workdir, capsys):
    assert run("frobnicate") != 0
    assert "invalid choice" in capsys.readouterr().err


def test_missing_arguments(workdir, capsys):
    assert run("commit") != 0          # -m is required
    assert "required" in capsys.readouterr().err
    assert run("add") != 0             # needs at least one path
    assert run("checkout") != 0        # needs a branch name
    assert run("reset") != 0           # needs a commit
    capsys.readouterr()


def test_no_command_prints_help(workdir, capsys):
    assert run() != 0
    assert "usage:" in capsys.readouterr().out


def test_add_nonexistent_path(repo, capsys):
    assert run("add", "does-not-exist.txt") != 0
    assert "did not match" in capsys.readouterr().err


def test_log_without_commits(repo, capsys):
    assert run("log") != 0
    assert "does not have any commits yet" in capsys.readouterr().err


def test_init_is_idempotent(workdir, capsys):
    assert run("init") == 0
    assert run("init") == 0  # re-init does not break anything
    assert (workdir / ".minigit" / "HEAD").is_file()
