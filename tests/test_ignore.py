""".minigitignore glob rules and the .minigit self-exclusion."""

import json

from conftest import run, write


def _index_paths(repo):
    data = json.loads((repo / ".minigit" / "index").read_text())
    return [e["path"] for e in data["entries"]]


def test_ignore_star_and_question_mark(repo):
    write(repo, ".minigitignore", "*.log\ntmp?\n")
    write(repo, "a.log", "x")
    write(repo, "tmp1", "x")
    write(repo, "tmp12", "x")   # '?' matches exactly one char -> not ignored
    write(repo, "keep.txt", "x")
    assert run("add", ".") == 0
    paths = _index_paths(repo)
    assert "a.log" not in paths
    assert "tmp1" not in paths
    assert "tmp12" in paths
    assert "keep.txt" in paths


def test_ignore_directory_pattern(repo):
    write(repo, ".minigitignore", "build/\n")
    write(repo, "build/out.bin", "x")
    write(repo, "build/nested/deep.txt", "x")
    write(repo, "src/main.py", "x")
    assert run("add", ".") == 0
    paths = _index_paths(repo)
    assert "build/out.bin" not in paths
    assert "build/nested/deep.txt" not in paths
    assert "src/main.py" in paths


def test_ignore_path_pattern_with_slash(repo):
    write(repo, ".minigitignore", "docs/*.md\n")
    write(repo, "docs/readme.md", "x")
    write(repo, "src/readme.md", "x")
    assert run("add", ".") == 0
    paths = _index_paths(repo)
    assert "docs/readme.md" not in paths
    assert "src/readme.md" in paths


def test_ignored_files_not_in_status_untracked(repo, capsys):
    write(repo, ".minigitignore", "*.log\n")
    write(repo, "debug.log", "x")
    write(repo, "real.txt", "x")
    capsys.readouterr()
    assert run("status", "--short") == 0
    out = capsys.readouterr().out
    assert "debug.log" not in out
    assert "?? real.txt" in out


def test_minigit_dir_never_indexed(repo):
    assert run("add", ".") == 0
    paths = _index_paths(repo)
    assert all(not p.startswith(".minigit") for p in paths)
