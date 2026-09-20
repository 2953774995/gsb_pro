"""CLI tests: run datamask-cli as a subprocess (module and script)."""

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "datamask-cli")


def run_cli(args, stdin=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "datamask.cli"] + args,
        capture_output=True,
        text=True,
        input=stdin,
        cwd=ROOT,
        env=env,
    )


def test_search_positions_count_and_groups():
    r = run_cli([r"1[3-9]\d{9}", "电话13812345678，备用13900001111"])
    assert r.returncode == 0
    assert "match 1: span=(2, 13) text='13812345678'" in r.stdout
    assert "match 2:" in r.stdout
    assert "total: 2 match(es)" in r.stdout


def test_capture_groups_printed():
    r = run_cli([r"(\d{4})-(\d{2})", "2026-09"])
    assert r.returncode == 0
    assert "groups=('2026', '09')" in r.stdout


def test_stdin_input():
    r = run_cli([r"\d+"], stdin="a1b22")
    assert r.returncode == 0
    assert "total: 2 match(es)" in r.stdout


def test_findall_option():
    r = run_cli([r"\d+", "--findall"], stdin="a1b22")
    assert r.returncode == 0
    assert "'1'" in r.stdout
    assert "'22'" in r.stdout


def test_ignore_case_option():
    r = run_cli(["-i", "abc", "xxABCxx"])
    assert r.returncode == 0
    assert "total: 1 match(es)" in r.stdout
    r = run_cli(["abc", "xxABCxx"])
    assert "total: 0 match(es)" in r.stdout


def test_multiline_option():
    r = run_cli(["-m", "^b", "a\nb\nc"])
    assert r.returncode == 0
    assert "total: 1 match(es)" in r.stdout
    r = run_cli(["^b", "a\nb\nc"])
    assert "total: 0 match(es)" in r.stdout


def test_file_option(tmp_path):
    f = tmp_path / "ticket.txt"
    f.write_text("手机13812345678", encoding="utf-8")
    r = run_cli([r"1[3-9]\d{9}", "--file", str(f)])
    assert r.returncode == 0
    assert "total: 1 match(es)" in r.stdout


def test_mask_option():
    r = run_cli(["--mask", "phone", "联系我 13812345678 谢谢"])
    assert r.returncode == 0
    assert r.stdout.strip() == "联系我 138****5678 谢谢"


def test_mask_option_from_stdin():
    r = run_cli(["--mask", "email"], stdin="邮箱 zhangsan@example.com")
    assert r.returncode == 0
    assert "z***@example.com" in r.stdout


def test_list_rules_option():
    r = run_cli(["--list-rules"])
    assert r.returncode == 0
    for name in ("phone", "idcard", "bankcard", "email"):
        assert name in r.stdout


def test_invalid_pattern_exit_code_and_message():
    r = run_cli(["(abc", "text"])
    assert r.returncode == 2
    assert "unterminated group" in r.stderr
    assert "column" in r.stderr


def test_unknown_mask_rule_exit_code():
    r = run_cli(["--mask", "nope", "text"])
    assert r.returncode == 2
    assert "unknown rule" in r.stderr


def test_missing_pattern_exit_code():
    r = run_cli([])
    assert r.returncode == 2


def test_max_steps_option():
    r = run_cli(["--max-steps", "1000", "(a+)+$", "a" * 20 + "b"])
    assert r.returncode == 2
    assert "step limit" in r.stderr


def test_executable_script():
    if not os.path.exists(SCRIPT):
        pytest.skip("datamask-cli script not found")
    r = subprocess.run(
        [SCRIPT, r"\d+", "a1b2"], capture_output=True, text=True, cwd=ROOT
    )
    assert r.returncode == 0
    assert "total: 2 match(es)" in r.stdout
