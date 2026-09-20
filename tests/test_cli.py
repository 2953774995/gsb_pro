"""End-to-end CLI tests through `python -m zipmini`."""

import os
import random
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(*args, cwd=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "zipmini", *args],
        capture_output=True, text=True, cwd=cwd, env=env,
    )


def test_create_list_extract_cycle(tmp_path):
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_bytes(b"alpha " * 100)
    (src / "sub" / "b.bin").write_bytes(random.Random(2).randbytes(2000))
    (src / "empty.txt").write_bytes(b"")

    archive = tmp_path / "out.zip"
    result = run_cli("c", str(archive), str(src))
    assert result.returncode == 0, result.stderr
    assert archive.exists()

    result = run_cli("l", str(archive))
    assert result.returncode == 0
    assert "src/a.txt" in result.stdout
    assert "src/sub/b.bin" in result.stdout
    assert "Length" in result.stdout and "Ratio" in result.stdout

    dest = tmp_path / "extracted"
    result = run_cli("x", str(archive), "-d", str(dest))
    assert result.returncode == 0, result.stderr
    assert (dest / "src" / "a.txt").read_bytes() == b"alpha " * 100
    assert (dest / "src" / "sub" / "b.bin").read_bytes() == (src / "sub" / "b.bin").read_bytes()
    assert (dest / "src" / "empty.txt").read_bytes() == b""


def test_create_multiple_inputs(tmp_path):
    f1 = tmp_path / "one.txt"
    f2 = tmp_path / "two.txt"
    f1.write_bytes(b"1" * 500)
    f2.write_bytes(b"2" * 500)
    archive = tmp_path / "multi.zip"
    result = run_cli("c", str(archive), str(f1), str(f2))
    assert result.returncode == 0, result.stderr
    result = run_cli("l", str(archive))
    assert "one.txt" in result.stdout
    assert "two.txt" in result.stdout


def test_extract_missing_archive_fails(tmp_path):
    result = run_cli("x", str(tmp_path / "nope.zip"), "-d", str(tmp_path))
    assert result.returncode != 0


def test_create_missing_input_fails(tmp_path):
    result = run_cli("c", str(tmp_path / "o.zip"), str(tmp_path / "missing"))
    assert result.returncode != 0
    assert "no such file" in result.stderr


def test_no_command_shows_usage():
    result = run_cli()
    assert result.returncode != 0
    assert "usage" in (result.stdout + result.stderr).lower()
