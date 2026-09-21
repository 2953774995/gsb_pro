import builtins
import contextlib
import io
import os

import pytest

from kbsearch.cli import main


@pytest.fixture()
def docs_dir(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "manual-fridge.txt").write_text(
        "冰箱维修手册\n冰箱压缩机异响时，先断电再检查压缩机固定螺栓。\n", encoding="utf-8"
    )
    (d / "manual-ac.txt").write_text(
        "空调维修手册\n空调不制冷多为冷媒泄漏，需要查漏补氟。\n", encoding="utf-8"
    )
    (d / "ticket-0001.txt").write_text(
        "工单0001\n客户反映冰箱不制冷，上门检查发现压缩机烧毁，已更换。\n", encoding="utf-8"
    )
    return str(d)


def run_cli(argv, stdin_lines):
    """Run cli.main with scripted stdin; return captured stdout."""
    lines = iter(stdin_lines)
    out = io.StringIO()

    def fake_input(prompt=""):
        out.write(prompt)
        try:
            return next(lines)
        except StopIteration:
            raise EOFError

    orig = builtins.input
    builtins.input = fake_input
    try:
        with contextlib.redirect_stdout(out):
            rc = main(argv)
    finally:
        builtins.input = orig
    return rc, out.getvalue()


def test_build_and_interactive_boolean_query(docs_dir, tmp_path):
    idx = str(tmp_path / "idx.json")
    rc, out = run_cli(
        ["--dir", docs_dir, "--index", idx],
        ["压缩机 AND (异响 OR 不制冷) NOT 空调", "quit"],
    )
    assert rc == 0
    assert os.path.exists(idx)
    assert "manual-fridge" in out
    assert "ticket-0001" in out
    assert "manual-ac" not in out.split("kbsearch>")[1]  # excluded by NOT 空调


def test_results_sorted_by_score(docs_dir, tmp_path):
    idx = str(tmp_path / "idx.json")
    rc, out = run_cli(["--dir", docs_dir, "--index", idx], ["压缩机 OR 冷媒", "quit"])
    assert rc == 0
    # scores must appear in non-increasing order
    import re

    scores = [float(s) for s in re.findall(r"score=([0-9.]+)", out)]
    assert scores and scores == sorted(scores, reverse=True)


def test_restart_without_rescan(docs_dir, tmp_path):
    idx = str(tmp_path / "idx.json")
    run_cli(["--dir", docs_dir, "--index", idx], ["quit"])
    # second process: load index only, no --dir
    rc, out = run_cli(["--index", idx], ["不制冷", "quit"])
    assert rc == 0
    assert "loaded 3 docs" in out
    assert "manual-ac" in out


def test_update_single_file(docs_dir, tmp_path):
    idx = str(tmp_path / "idx.json")
    run_cli(["--dir", docs_dir, "--index", idx], ["quit"])
    target = os.path.join(docs_dir, "ticket-0001.txt")
    with open(target, "w", encoding="utf-8") as fh:
        fh.write("工单0001\n客户反映洗衣机漏水，更换密封圈。\n")
    assert main(["--index", idx, "--update", target]) == 0
    # query after update: old term gone, new term hits
    rc2, out2 = run_cli(["--index", idx], ["压缩机", "洗衣机", "quit"])
    assert "ticket-0001" not in out2.split("kbsearch>")[1].split("kbsearch>")[0]
    assert "ticket-0001" in out2


def test_reindex(docs_dir, tmp_path):
    idx = str(tmp_path / "idx.json")
    run_cli(["--dir", docs_dir, "--index", idx], ["quit"])
    os.remove(os.path.join(docs_dir, "ticket-0001.txt"))
    rc, out = run_cli(["--dir", docs_dir, "--index", idx, "--reindex"], ["quit"])
    assert rc == 0
    assert "2 docs total" in out


def test_synonyms_flag(docs_dir, tmp_path):
    syn = tmp_path / "syn.txt"
    syn.write_text("冰箱=冰柜\n", encoding="utf-8")
    idx = str(tmp_path / "idx.json")
    rc, out = run_cli(
        ["--dir", docs_dir, "--index", idx, "--synonyms", str(syn)],
        ["冰柜", "quit"],
    )
    assert rc == 0
    assert "manual-fridge" in out


def test_query_error_reported(docs_dir, tmp_path):
    idx = str(tmp_path / "idx.json")
    rc, out = run_cli(["--dir", docs_dir, "--index", idx], ["压缩机 AND", "quit"])
    assert "query error" in out
