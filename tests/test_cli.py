"""End-to-end tests for the rex-cli command line interface."""

import subprocess
import sys

import pytest


def run_cli(args, stdin_text=None):
    return subprocess.run(
        [sys.executable, "-m", "rex"] + args,
        capture_output=True,
        text=True,
        input=stdin_text,
    )


def test_cli_basic_search_with_groups():
    result = run_cli([r"(\w+)@(\w+)", "contact alice@example.org"])
    assert result.returncode == 0
    assert "span=(8, 21)" in result.stdout
    assert "text='alice@example'" in result.stdout
    assert "group 1: 'alice'" in result.stdout
    assert "group 2: 'example'" in result.stdout
    assert "total matches: 1" in result.stdout


def test_cli_no_match():
    result = run_cli(["zzz", "hello"])
    assert result.returncode == 1
    assert "total matches: 0" in result.stdout


def test_cli_stdin_and_ignore_case():
    result = run_cli(["-i", "HELLO"], stdin_text="say hello\n")
    assert result.returncode == 0
    assert "text='hello'" in result.stdout


def test_cli_findall_counts_matches():
    result = run_cli(["--findall", r"\d+", "a1 b22 c333"])
    assert result.returncode == 0
    assert result.stdout.count("match ") == 3
    assert "total matches: 3" in result.stdout


def test_cli_multiline():
    result = run_cli(
        ["--multiline", "--findall", "^b"], stdin_text="ab\nba\nbb\n"
    )
    assert result.returncode == 0
    assert "total matches: 2" in result.stdout


def test_cli_file_option(tmp_path):
    data = tmp_path / "data.txt"
    data.write_text("x=1\ny=22\n", encoding="utf-8")
    result = run_cli(["--findall", r"(\w+)=(\d+)", "--file", str(data)])
    assert result.returncode == 0
    assert "group 1: 'x'" in result.stdout
    assert "group 2: '22'" in result.stdout
    assert "total matches: 2" in result.stdout


def test_cli_invalid_pattern_exit_code():
    result = run_cli(["(abc", "abc"])
    assert result.returncode == 2
    assert "invalid pattern" in result.stderr
    assert "column" in result.stderr


def test_cli_timeout_exit_code():
    result = run_cli(
        ["(a+)+$", "a" * 25 + "b", "--step-limit", "50000"]
    )
    assert result.returncode == 3
    assert "step limit" in result.stderr


def test_cli_named_groups():
    result = run_cli([r"(?P<word>\w+)", "hello"])
    assert result.returncode == 0
    assert "group 'word': 'hello'" in result.stdout
