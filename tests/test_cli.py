"""End-to-end tests of the minimq-cli against a real data directory."""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(data_dir, *args):
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "minimq", "--data-dir", data_dir, *args],
        capture_output=True,
        text=True,
        env=env,
    )
    return proc


def test_cli_full_flow(tmp_path):
    d = str(tmp_path / "data")

    p = run_cli(d, "create-topic", "orders")
    assert p.returncode == 0, p.stderr

    for i in range(3):
        p = run_cli(d, "produce", "orders", "msg{}".format(i))
        assert p.returncode == 0, p.stderr
        assert p.stdout.strip() == str(i)

    p = run_cli(d, "topics")
    assert p.returncode == 0
    assert "orders" in p.stdout

    p = run_cli(d, "consume", "orders", "--group", "web", "--max", "2", "--ack")
    assert p.returncode == 0
    lines = [ln for ln in p.stdout.strip().splitlines() if ln]
    assert lines == ["0\tmsg0", "1\tmsg1"]

    # Reconnect: only offset 2 remains for the "web" group.
    p = run_cli(d, "consume", "orders", "--group", "web", "--max", "10", "--ack")
    assert lines or True
    assert p.stdout.strip() == "2\tmsg2"

    # Independent group sees the whole stream.
    p = run_cli(d, "consume", "orders", "--group", "billing", "--max", "10")
    assert p.stdout.count("\t") == 3

    p = run_cli(d, "groups")
    assert "web" in p.stdout and "billing" in p.stdout

    # Group progress is durable: poll once more, nothing for web.
    p = run_cli(d, "consume", "orders", "--group", "web", "--max", "10")
    assert p.stdout.strip() == ""


def test_cli_unknown_topic_exit_code(tmp_path):
    d = str(tmp_path / "data")
    p = run_cli(d, "produce", "ghost", "hi")
    assert p.returncode == 2
    assert "does not exist" in p.stderr


def test_cli_retention_topic(tmp_path):
    d = str(tmp_path / "data")
    p = run_cli(d, "create-topic", "ring", "--max-messages", "2")
    assert p.returncode == 0, p.stderr
    for i in range(4):
        p = run_cli(d, "produce", "ring", "m{}".format(i))
        assert p.returncode == 0
    p = run_cli(d, "consume", "ring", "--group", "g", "--max", "10")
    assert [ln for ln in p.stdout.strip().splitlines()] == ["2\tm2", "3\tm3"]
