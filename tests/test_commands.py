from __future__ import annotations

import io
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from cfgvault.cli import main
from cfgvault.ignore import IgnoreRules
from cfgvault.refs import read_branch


class Result:
    def __init__(self, code, stdout, stderr):
        self.code = code
        self.stdout = stdout
        self.stderr = stderr


def run_cli(tmp_path: Path, *args: str) -> Result:
    out = io.StringIO()
    err = io.StringIO()
    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args), out=out, err=err)
    finally:
        os.chdir(old)
    return Result(code, out.getvalue(), err.getvalue())


def write(path: Path, text: str = "x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def init_with_file(tmp_path: Path, rel: str, content: str) -> Result:
    write(tmp_path / rel, content)
    run_cli(tmp_path, "init")
    return run_cli(tmp_path, "add", rel)


def test_status_staged_modified_deleted_untracked_short(tmp_path):
    init_with_file(tmp_path, "staged.json", "{}\n")
    run_cli(tmp_path, "snap", "-m", "base")

    write(tmp_path / "new.json", "new\n")
    write(tmp_path / "modified.json", "old\n")
    run_cli(tmp_path, "add", "new.json", "modified.json")
    run_cli(tmp_path, "snap", "-m", "more")

    write(tmp_path / "modified.json", "changed\n")
    write(tmp_path / "untracked.json", "u\n")
    (tmp_path / "staged.json").unlink()
    # Stage deletion for staged.json; modified remains unstaged.
    run_cli(tmp_path, "add", "staged.json")
    result = run_cli(tmp_path, "status", "--short")
    assert result.code == 0
    assert "D  staged.json" in result.stdout
    assert " M modified.json" in result.stdout
    assert "?? untracked.json" in result.stdout

    long_status = run_cli(tmp_path, "status")
    assert "deleted:  staged.json" in long_status.stdout
    assert "modified: modified.json" in long_status.stdout
    assert "Untracked files:" in long_status.stdout


def test_diff_insert_delete_modify_and_swapped_lines_stat(tmp_path):
    write(tmp_path / "swap.txt", "one\ntwo\n")
    write(tmp_path / "edit.txt", "a\nb\nc\n")
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "add", ".")
    run_cli(tmp_path, "snap", "-m", "base")

    write(tmp_path / "swap.txt", "two\none\n")
    write(tmp_path / "edit.txt", "a\nB\nc\nd\n")
    diff = run_cli(tmp_path, "diff")
    assert diff.code == 0
    assert "@@ -1,2 +1,2 @@" in diff.stdout
    assert "-two" in diff.stdout
    assert "+two" in diff.stdout
    assert "-b" in diff.stdout
    assert "+B" in diff.stdout
    assert "+d" in diff.stdout

    stat = run_cli(tmp_path, "diff", "--stat")
    assert "1+/1-" in stat.stdout
    assert "2+/1-" in stat.stdout
    assert "insertion(s)(+)" in stat.stdout


def test_diff_cached_and_two_refs(tmp_path):
    write(tmp_path / "a.txt", "old\n")
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "add", "a.txt")
    run_cli(tmp_path, "snap", "-m", "v1")
    write(tmp_path / "a.txt", "new\n")
    run_cli(tmp_path, "add", "a.txt")
    cached = run_cli(tmp_path, "diff", "--cached")
    assert "-old" in cached.stdout and "+new" in cached.stdout
    run_cli(tmp_path, "snap", "-m", "v2")
    run_cli(tmp_path, "snap", "-m", "v2")
    history = [line.split()[0] for line in run_cli(tmp_path, "log", "--oneline").stdout.splitlines()]
    two_refs = run_cli(tmp_path, "diff", history[1], history[0])
    assert two_refs.code == 0
    assert "-old" in two_refs.stdout and "+new" in two_refs.stdout


def test_ignore_basic_globs_directory_and_anchored_patterns():
    rules = IgnoreRules(
        ["*.tmp", "cache/", "/poster/local.txt", "build/output/*.png", "draft?.txt"]
    )
    assert rules.matches("anywhere/file.tmp")
    assert not rules.matches("file.tmp/child", is_dir=False)
    assert rules.matches("cache", is_dir=True)
    assert rules.matches("nested/cache", is_dir=True)
    assert rules.matches("poster/local.txt")
    assert not rules.matches("other/local.txt")
    assert rules.matches("build/output/poster.png")
    assert not rules.matches("build/output/nested/poster.png")
    assert rules.matches("draft1.txt")
    assert not rules.matches("draft12.txt")
    # The repository metadata directory is always ignored.
    assert rules.matches(".cfgvault/objects/ab/cd")


def test_add_and_status_skip_cfgvaultignore_matches(tmp_path):
    write(tmp_path / "prices.json", "{}\n")
    write(tmp_path / "ignore.tmp", "secret scratch\n")
    write(tmp_path / "cache" / "a.tmp", "x\n")
    write(tmp_path / ".cfgvaultignore", "*.tmp\ncache/\n")
    run_cli(tmp_path, "init")
    add = run_cli(tmp_path, "add", ".")
    assert "ignore.tmp" not in add.stdout
    assert "cache/a.tmp" not in add.stdout
    run_cli(tmp_path, "snap", "-m", "base")
    assert run_cli(tmp_path, "status", "--short").stdout.strip() == "## main\nclean working tree"
    assert ".cfgvault" not in run_cli(tmp_path, "add", ".cfgvault").stdout


def test_reset_soft_and_mixed_semantics(tmp_path):
    write(tmp_path / "a.txt", "v1\n")
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "add", ".")
    run_cli(tmp_path, "snap", "-m", "v1")
    first = read_branch(tmp_path, "main")

    write(tmp_path / "a.txt", "v2\n")
    run_cli(tmp_path, "add", "a.txt")
    run_cli(tmp_path, "snap", "-m", "v2")

    soft = run_cli(tmp_path, "reset", "--soft", first)
    assert soft.code == 0
    assert read_branch(tmp_path, "main") == first
    # Index and worktree remain at v2, hence v2 is staged.
    assert "M  a.txt" in run_cli(tmp_path, "status", "--short").stdout

    mixed = run_cli(tmp_path, "reset", "--mixed", first)
    assert mixed.code == 0
    status = run_cli(tmp_path, "status", "--short").stdout
    assert " M a.txt" in status
    assert (tmp_path / "a.txt").read_text() == "v2\n"


def test_uninitialized_unknown_args_and_bad_refs_return_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(["status"], out=out, err=err)
    assert code == 1
    assert "run 'cfgvault init' first" in err.getvalue()

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(["nope"], out=out, err=err)
    assert code == 2

    run_cli(tmp_path, "init")
    missing_snapshot = run_cli(tmp_path, "reset", "--soft", "deadbeef")
    assert missing_snapshot.code == 1
    assert "unknown snapshot reference" in missing_snapshot.stderr

    missing_branch = run_cli(tmp_path, "checkout", "missing")
    assert missing_branch.code == 1
    assert "branch does not exist" in missing_branch.stderr

    missing_param = run_cli(tmp_path, "snap")
    assert missing_param.code == 2


def test_add_deleted_nonexistent_unknown_path_error(tmp_path):
    run_cli(tmp_path, "init")
    result = run_cli(tmp_path, "add", "missing.json")
    assert result.code == 1
    assert "path does not exist" in result.stderr


def test_add_cfgvault_directory_is_explicit_error_and_checkout_protects_untracked(tmp_path):
    write(tmp_path / "a.txt", "base\n")
    run_cli(tmp_path, "init")
    result = run_cli(tmp_path, "add", ".cfgvault")
    assert result.code == 1
    assert "can never be tracked" in result.stderr
    run_cli(tmp_path, "add", ".")
    run_cli(tmp_path, "snap", "-m", "base")
    run_cli(tmp_path, "branch", "promo")
    run_cli(tmp_path, "checkout", "promo")
    write(tmp_path / "new.txt", "promo\n")
    run_cli(tmp_path, "add", "new.txt")
    run_cli(tmp_path, "snap", "-m", "promo")
    write(tmp_path / "new.txt", "local untracked overwrite would lose data\n")
    # It is tracked in the currently checked-out promo, so simulate returning
    # to main where it is absent; then create an untracked collision for promo.
    run_cli(tmp_path, "checkout", "main")
    write(tmp_path / "new.txt", "local untracked overwrite would lose data\n")
    result = run_cli(tmp_path, "checkout", "promo")
    assert result.code == 1
    assert "refusing to overwrite untracked file" in result.stderr


def test_chinese_scheme_branch_names_are_supported(tmp_path):
    write(tmp_path / "poster.txt", "日常版\n")
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "add", ".")
    run_cli(tmp_path, "snap", "-m", "日常版快照")
    assert run_cli(tmp_path, "branch", "大促版").code == 0
    assert run_cli(tmp_path, "checkout", "大促版").code == 0
    assert "* 大促版" in run_cli(tmp_path, "branch").stdout
    assert (tmp_path / ".cfgvault" / "refs" / "heads" / "大促版").exists()


def test_git_metadata_directory_is_never_added(tmp_path):
    write(tmp_path / "config.json", "{}\n")
    (tmp_path / ".git").mkdir()
    write(tmp_path / ".git" / "HEAD", "ref\n")
    run_cli(tmp_path, "init")
    result = run_cli(tmp_path, "add", ".")
    assert ".git/HEAD" not in result.stdout
    run_cli(tmp_path, "snap", "-m", "base")
    status = run_cli(tmp_path, "status", "--short")
    assert ".git" not in status.stdout
