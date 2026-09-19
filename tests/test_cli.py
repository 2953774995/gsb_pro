"""End-to-end tests for the minimq-cli command line tool."""

import pytest

from minimq.cli import main


def run_cli(capsys, data_dir, *argv):
    code = main(["--data-dir", str(data_dir)] + list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_produce_consume_topics_flow(tmp_path, capsys):
    data_dir = tmp_path / "mq"

    code, out, _ = run_cli(capsys, data_dir, "create", "events")
    assert code == 0 and "created" in out

    code, out, _ = run_cli(capsys, data_dir, "produce", "events", "hello")
    assert code == 0 and "offset 0" in out
    code, out, _ = run_cli(capsys, data_dir, "produce", "events", "world")
    assert code == 0 and "offset 1" in out

    code, out, _ = run_cli(capsys, data_dir, "topics")
    assert code == 0
    assert "events" in out and "next_offset=2" in out

    code, out, _ = run_cli(capsys, data_dir, "consume", "events",
                           "-g", "g1", "-n", "2")
    assert code == 0
    assert "0\thello" in out.replace("events:0", "0") or "hello" in out
    assert "world" in out

    # Acked messages are not consumed again (state on disk).
    code, out, err = run_cli(capsys, data_dir, "consume", "events",
                             "-g", "g1", "-n", "2")
    assert code == 0
    assert "hello" not in out

    # A different group still sees everything.
    code, out, _ = run_cli(capsys, data_dir, "consume", "events",
                           "-g", "g2", "-n", "2")
    assert "hello" in out and "world" in out


def test_produce_auto_create(tmp_path, capsys):
    data_dir = tmp_path / "mq"
    code, out, _ = run_cli(capsys, data_dir, "produce", "t", "x", "--create")
    assert code == 0
    code, out, _ = run_cli(capsys, data_dir, "topics")
    assert "t" in out


def test_cli_errors(tmp_path, capsys):
    data_dir = tmp_path / "mq"
    code, _, err = run_cli(capsys, data_dir, "produce", "missing", "x")
    assert code == 1 and "does not exist" in err

    code, _, err = run_cli(capsys, data_dir, "consume", "missing")
    assert code == 1 and "does not exist" in err
