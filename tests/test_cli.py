import subprocess
import sys
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(args, stdin_text=""):
    return subprocess.run(
        [sys.executable, "-m", "minisearch"] + args,
        input=stdin_text, capture_output=True, text=True,
        cwd=REPO_ROOT, timeout=60)


def test_cli_indexes_and_searches(tmp_path):
    (tmp_path / "python.txt").write_text(
        "Python Guide\nPython is a language for web servers and data.\n",
        encoding="utf-8")
    (tmp_path / "java.txt").write_text(
        "Java Guide\nJava is a language for enterprise servers.\n",
        encoding="utf-8")
    (tmp_path / "notes.txt").write_text(
        "笔记\n我喜欢用搜索引擎。\n", encoding="utf-8")
    (tmp_path / "ignore.md").write_text("not indexed\n", encoding="utf-8")

    proc = run_cli([str(tmp_path)], "python AND NOT java\nquit\n")
    assert proc.returncode == 0, proc.stderr
    assert "Indexed 3 document(s)" in proc.stdout
    assert "python.txt" in proc.stdout
    assert "java.txt" not in proc.stdout
    assert "Python Guide" in proc.stdout  # title shown

    proc = run_cli([str(tmp_path)], "搜索引擎\nquit\n")
    assert "notes.txt" in proc.stdout

    proc = run_cli([str(tmp_path)], "AND OR\nquit\n")
    assert "query error" in proc.stdout


def test_cli_bad_directory():
    proc = run_cli(["/nonexistent-dir-xyz"], "")
    assert proc.returncode == 2
    assert "not a directory" in proc.stderr


def test_cli_executable_script(tmp_path):
    (tmp_path / "a.txt").write_text("hello search world\n", encoding="utf-8")
    script = os.path.join(REPO_ROOT, "minisearch-cli")
    proc = subprocess.run(
        [script, str(tmp_path)], input="search\nquit\n",
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "a.txt" in proc.stdout
