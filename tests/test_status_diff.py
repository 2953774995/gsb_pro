from __future__ import annotations

import re
from pathlib import Path


from cfgvault.repo import find_repository
from conftest import write


def snapshot_oid(result):
    match = re.search(r"\b[0-9a-f]{40}\b", result.stdout)
    assert match
    return match.group(0)


def setup_baseline(run_cli):
    run_cli("init")
    write("tracked.txt", "same\n")
    write("config/price.json", "price\n")
    run_cli("add", ".")
    run_cli("snap", "-m", "base")


def test_status_reports_staged_modified_deleted_and_untracked(run_cli):
    setup_baseline(run_cli)

    write("added.txt", "new\n")
    write("tracked.txt", "same\nchanged\n")
    Path("config/price.json").unlink()

    human = run_cli("status").stdout
    assert "Changes to be committed" not in human
    assert "modified: tracked.txt" in human
    assert "deleted: config/price.json" in human
    assert "added.txt" in human

    short = run_cli("status", "--short").stdout.splitlines()
    assert " M tracked.txt" in short
    assert " D config/price.json" in short
    assert "?? added.txt" in short

    run_cli("add", "tracked.txt")
    short = run_cli("status", "--short").stdout
    assert "M  tracked.txt" in short
    run_cli("add", "config/price.json")
    short = run_cli("status", "--short").stdout
    assert "D  config/price.json" in short

    run_cli("add", "added.txt")
    short = run_cli("status", "--short").stdout
    assert "A  added.txt" in short


def test_default_diff_compares_worktree_to_index_with_context_and_swaps(run_cli):
    setup_baseline(run_cli)
    # Establish an eight-line baseline so three lines of surrounding context
    # appear in the hunk.
    write(
        "tracked.txt",
        "context0\nA\nB\nC\nD\ncontext5\ncontext6\ncontext7\n",
    )
    run_cli("add", "tracked.txt")
    run_cli("snap", "-m", "multi-line baseline")
    # Swap/replace one interior line; sequence matcher gives delete/add,
    # delete/add, rather than treating the file as entirely unrelated.
    write(
        "tracked.txt",
        "context0\nD\nB\nC\nA\ncontext5\ncontext6\ncontext7\n",
    )
    result = run_cli("diff")
    assert result.code == 0
    assert "@@ -1,8 +1,8 @@" in result.stdout
    assert "-A" in result.stdout
    assert "-D" in result.stdout
    assert "+D" in result.stdout
    assert "+A" in result.stdout
    assert " context0" in result.stdout
    assert " context6" in result.stdout


def test_diff_handles_added_and_deleted_files_and_stat(run_cli):
    setup_baseline(run_cli)
    write("new.txt", "n1\nn2\n")
    Path("tracked.txt").unlink()

    result = run_cli("diff")
    assert "-same" in result.stdout
    assert "+n1" in result.stdout
    assert "+n2" in result.stdout
    assert "@@ -1 +0,0 @@" in result.stdout

    stat = run_cli("diff", "--stat").stdout
    assert "tracked.txt |    1  +0 -1 -" in stat
    assert "new.txt     |    2  +2 -0 ++" in stat
    assert "2 files changed, 2 insertion(s)(+), 1 deletion(s)(-)" in stat


def test_cached_diff_compares_index_to_head(run_cli):
    setup_baseline(run_cli)
    write("tracked.txt", "updated\n")
    result = run_cli("diff", "--cached")
    assert result.stdout == ""
    run_cli("add", "tracked.txt")
    result = run_cli("diff", "--cached")
    assert "-same" in result.stdout
    assert "+updated" in result.stdout


def test_cfgvaultignore_basic_globs_affect_add_and_status(run_cli):
    run_cli("init")
    write(".cfgvaultignore", "*.tmp\ncache/\n/fixed.txt\nnested/*.json\n")
    write("price/a.tmp", "ignored\n")
    write("cache/x/y.txt", "ignored nested\n")
    write("fixed.txt", "root only\n")
    write("else/fixed.txt", "not ignored\n")
    write("nested/deal.json", "ignored nested glob\n")
    write("other/nested/deal.json", "kept\n")
    write("real.json", "kept\n")

    run_cli("add", ".")
    index = {entry.path for entry in __import__("cfgvault.index", fromlist=["read_index"]).read_index(find_repository()).entries()}
    assert index == {"else/fixed.txt", "other/nested/deal.json", "real.json", ".cfgvaultignore"}

    short = run_cli("status", "--short").stdout
    assert "a.tmp" not in short
    assert "cache/x/y.txt" not in short
    assert not any(line.split(" ", 1)[-1] == "fixed.txt" for line in short.splitlines()[1:])
    assert not any(line.split(" ", 1)[-1] == "nested/deal.json" for line in short.splitlines()[1:])
    assert "?? else/fixed.txt" in short or "A  else/fixed.txt" in short


def test_cfgvault_directory_is_never_added(run_cli):
    run_cli("init")
    write("config/a.json", "a")
    result = run_cli("add", ".cfgvault")
    assert result.code != 0
    assert ".cfgvault" in result.stderr
