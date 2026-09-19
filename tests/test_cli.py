"""End-to-end CLI tests."""

import subprocess
import sys

import pytest

from minidiff.cli import main

PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_cli_diff_bare_form(capsys):
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        a = write(__import__("pathlib").Path(tmp), "a.txt", "a\nb\n")
        b = write(__import__("pathlib").Path(tmp), "b.txt", "a\nB\n")
        rc = main([str(a), str(b)])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("--- ")
    assert "-b\n" in out
    assert "+B\n" in out


def test_cli_diff_explicit_subcommand(capsys, tmp_path):
    a = write(tmp_path, "a", "x\n")
    b = write(tmp_path, "b", "y\n")
    assert main(["diff", str(a), str(b), "-U", "0"]) == 0
    out = capsys.readouterr().out
    assert "@@ -1 +1 @@" in out


def test_cli_apply_writes_result(tmp_path, capsys):
    a = write(tmp_path, "orig", "one\ntwo\nthree\n")
    b_text = "one\nTWO\nthree\n"
    b = write(tmp_path, "rev", b_text)
    main([str(a), str(b)])
    patch_text = capsys.readouterr().out
    patch = write(tmp_path, "p.diff", patch_text)

    assert main(["apply", str(patch), str(a)]) == 0
    assert capsys.readouterr().out == b_text

    out_file = tmp_path / "result"
    assert main(["--apply", str(patch), str(a), "-o", str(out_file)]) == 0
    assert out_file.read_text() == b_text


def test_cli_apply_reverse_and_fuzz(tmp_path, capsys):
    a = write(tmp_path, "a", "a\nb\nc\n")
    b = write(tmp_path, "b", "a\nB\nc\n")
    main([str(a), str(b), "-U", "0"])
    patch = write(tmp_path, "p", capsys.readouterr().out)

    shifted = write(tmp_path, "shifted", "PRE\na\nB\nc\n")
    with pytest.raises(SystemExit) if False else pytest.MonkeyPatch.context():
        pass
    # strict apply fails with exit code 2
    rc = main(["apply", str(patch), str(shifted), "-R"])
    assert rc == 2
    capsys.readouterr()
    # reverse + fuzz succeeds
    rc = main(["apply", str(patch), str(shifted), "-R", "--fuzz"])
    assert rc == 0
    assert capsys.readouterr().out == "PRE\na\nb\nc\n"


def test_cli_similarity(tmp_path, capsys):
    a = write(tmp_path, "a", "a\nb\n")
    b = write(tmp_path, "b", "a\nc\n")
    assert main(["similarity", str(a), str(b)]) == 0
    assert float(capsys.readouterr().out.strip()) == pytest.approx(0.5)


def test_cli_missing_file_returns_2(tmp_path):
    assert main(["diff", str(tmp_path / "nope"), str(tmp_path / "nope2")]) == 2


def test_module_invocation_subprocess(tmp_path):
    a = write(tmp_path, "a.txt", "hello\n")
    b = write(tmp_path, "b.txt", "hello\nworld\n")
    result = subprocess.run(
        [sys.executable, "-m", "minidiff", str(a), str(b)],
        cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "+world" in result.stdout

    patch = write(tmp_path, "p.diff", result.stdout)
    result = subprocess.run(
        [sys.executable, "-m", "minidiff", "apply",
         str(patch), str(a)],
        cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "hello\nworld\n"
