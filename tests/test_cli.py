import subprocess
import sys
from pathlib import Path

import pytest

from minidiff.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_cli_diff_and_apply(tmp_path, capsys):
    old = tmp_path / "old.txt"
    new = tmp_path / "new.txt"
    patch = tmp_path / "change.diff"
    patched = tmp_path / "patched.txt"
    old.write_text("a\nb\nc\n", encoding="utf-8")
    new.write_text("a\nB\nc\n", encoding="utf-8")

    assert main([str(old), str(new), "-c", "2", "-o", str(patch)]) == 0
    assert patch.read_text(encoding="utf-8").startswith("--- ")
    assert main(["--apply", str(patch), str(old), "-o", str(patched)]) == 0
    assert patched.read_text(encoding="utf-8") == new.read_text(encoding="utf-8")
    assert main(
        [
            "--apply",
            str(patch),
            str(new),
            "--reverse",
            "-o",
            str(tmp_path / "restored.txt"),
        ]
    ) == 0
    assert (tmp_path / "restored.txt").read_text(encoding="utf-8") == old.read_text()


def test_cli_identical_diff_writes_nothing(tmp_path, capsys):
    old = tmp_path / "a"
    new = tmp_path / "b"
    old.write_text("same\n")
    new.write_text("same\n")
    assert main([str(old), str(new)]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_cli_apply_error_returns_nonzero(tmp_path):
    original = tmp_path / "orig"
    patch = tmp_path / "patch"
    original.write_text("bad\n")
    patch.write_text(
        "--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new\n"
    )
    assert main(["--apply", str(patch), str(original)]) == 1


def test_executable_launcher_and_module_invocation(tmp_path):
    old = tmp_path / "a.txt"
    new = tmp_path / "b.txt"
    old.write_text("x\n")
    new.write_text("y\n")

    launcher = subprocess.run(
        [sys.executable, str(ROOT / "minidiff-cli"), str(old), str(new)],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "-x" in launcher.stdout
    assert "+y" in launcher.stdout

    module = subprocess.run(
        [sys.executable, "-m", "minidiff", str(old), str(new), "--context", "0"],
        text=True,
        capture_output=True,
        check=True,
        cwd=ROOT,
    )
    assert module.stdout.splitlines()[-2:] == ["-x", "+y"]


def test_cli_argument_validation(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main([str(tmp_path)])
    assert exc.value.code == 2
