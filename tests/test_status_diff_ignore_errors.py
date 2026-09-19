from pathlib import Path

import pytest

from minigit import index as index_mod
from minigit import objects, refs
from minigit.cli import main
from minigit.commits import read_commit
from minigit.ignore import IgnoreRules, parse_pattern
from minigit.repository import Repository


def run(*args, expect=0):
    code = main(list(args))
    assert code == expect
    return code


def write(name, content=""):
    path = Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def initial_commit():
    write("a.txt", "one\n")
    write("d/keep.txt", "kept\n")
    run("add", ".")
    run("commit", "-m", "initial")


def test_status_reports_staged_modified_deleted_and_untracked(repo, capsys):
    initial_commit()
    write("a.txt", "one changed\n")
    Path("d/keep.txt").unlink()
    write("new.txt", "new\n")
    run("status", "--short")
    output = capsys.readouterr().out.splitlines()
    assert " M a.txt" in output
    assert " D d/keep.txt" in output
    assert "?? new.txt" in output

    run("add", "a.txt", "new.txt")
    run("status", "--short")
    staged = capsys.readouterr().out.splitlines()
    assert "M  a.txt" in staged
    assert "A  new.txt" in staged
    assert "D  d/keep.txt" not in staged  # deletion has not been staged yet
    run("add", "d/keep.txt")
    run("status", "--short")
    assert "D  d/keep.txt" in capsys.readouterr().out


def test_default_diff_compares_worktree_to_index_and_stat_counts(repo, capsys):
    write("a.txt", "one\ntwo\nthree\n")
    write("b.txt", "delete me\n")
    run("add", ".")
    write("a.txt", "zero\none\nthree\nfour\n")
    Path("b.txt").unlink()

    run("diff")
    patch = capsys.readouterr().out
    assert "diff" not in patch
    assert "--- a/a.txt" in patch and "+++ b/a.txt" in patch
    assert "@@ -1,3 +1,4 @@" in patch
    assert "-two" in patch and "+zero" in patch and "+four" in patch
    assert " one" in patch and " three" in patch
    assert "--- a/b.txt" in patch and "-delete me" in patch

    run("diff", "--stat")
    stat = capsys.readouterr().out
    assert "a.txt |" in stat and "b.txt |" in stat
    assert "2 insertions(+)" in stat
    assert "2 deletions(-)" in stat


def test_swapped_lines_produce_correct_remove_and_add_diff(repo, capsys):
    write("swap.txt", "first\nsecond\n")
    run("add", "swap.txt")
    write("swap.txt", "second\nfirst\n")
    run("diff")
    patch = capsys.readouterr().out
    assert patch.count("+second") == 1
    assert patch.count("-second") == 1
    assert " first" in patch
    run("diff", "--stat")
    stat = capsys.readouterr().out
    assert "1 insertion(+)" in stat
    assert "1 deletion(-)" in stat


def test_cached_diff_compares_index_to_head(repo, capsys):
    initial_commit()
    write("a.txt", "staged\n")
    run("add", "a.txt")
    write("a.txt", "unstaged after staging\n")
    run("diff", "--cached")
    cached = capsys.readouterr().out
    assert "+staged" in cached
    assert "unstaged" not in cached
    run("diff")
    worktree = capsys.readouterr().out
    assert "-staged" in worktree and "+unstaged after staging" in worktree


def test_minigitignore_glob_directory_anchored_prefix_and_suffix(repo):
    write(".minigitignore", "*.log\nbuild/\n/config-root.txt\ndocs/*.md\nprefix*\n*suffix.tmp\n")
    rules = IgnoreRules.from_file(Path(".minigitignore"))
    for path, is_dir in [
        ("nested/app.log", False),
        ("build", True),
        ("nested/build", True),
        ("config-root.txt", False),
        ("docs/readme.md", False),
        ("prefix-file", False),
        ("deep/prefixfile", False),
        ("thing-suffix.tmp", False),
    ]:
        assert rules.is_ignored(path, is_dir), path
    for path, is_dir in [
        ("nested/config-root.txt", False),
        ("docs/nested/readme.md", False),
        ("log.txt", False),
        ("ordinary.txt", False),
    ]:
        assert not rules.is_ignored(path, is_dir), path
    assert parse_pattern("?") is not None


def test_add_and_status_skip_ignored_files_but_never_minigit_dir(repo, capsys):
    write(".minigitignore", "*.log\nignored-dir/\n")
    write("tracked.txt", "tracked\n")
    write("secret.log", "secret\n")
    write("ignored-dir/note.txt", "x\n")
    write(".minigit/objects/xx/fake", "never tracked\n")
    run("add", ".")
    run("commit", "-m", "ignored setup")
    capsys.readouterr()
    entries = index_mod.read_index(Repository(repo).index_file)
    assert set(entries) == {".minigitignore", "tracked.txt"}
    run("status", "--short")
    output = capsys.readouterr().out
    assert "secret.log" not in output and "ignored-dir" not in output
    assert not output.strip()


def test_uninitialized_command_has_clear_nonzero_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["status"]) == 1
    error = capsys.readouterr().err
    assert "not a minigit repository" in error
    assert main(["frobnicate"]) == 1
    assert "unknown command" in capsys.readouterr().err
    assert main(["commit"]) == 1
    assert "commit requires" in capsys.readouterr().err


def test_invalid_paths_and_checkout_errors_return_nonzero(repo, capsys):
    initial_commit()
    run("add", "missing.txt", expect=1)
    assert "path does not exist" in capsys.readouterr().err
    run("checkout", expect=1)
    assert "checkout requires" in capsys.readouterr().err
    run("reset", "--hard", "HEAD", expect=1)
    assert "unknown reset option" in capsys.readouterr().err
