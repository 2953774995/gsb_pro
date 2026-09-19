"""End-to-end tests for the regexlab-cli command."""

import subprocess
import sys


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "regexlab.cli", *args],
        capture_output=True, text=True)


def test_cli_match_success():
    result = run_cli(r"a(b+)c", "abbc")
    assert result.returncode == 0
    assert "MATCH" in result.stdout
    assert "'abbc'" in result.stdout
    assert "group 1: 'bb'" in result.stdout


def test_cli_no_match_exit_code():
    result = run_cli("xyz", "abc")
    assert result.returncode == 1
    assert "NO MATCH" in result.stdout


def test_cli_invalid_pattern_exit_code():
    result = run_cli("(unclosed", "abc")
    assert result.returncode == 2
    assert "Pattern error" in result.stderr


def test_cli_findall_mode():
    result = run_cli("--mode", "findall", r"\d+", "a1b22")
    assert result.returncode == 0
    assert "['1', '22']" in result.stdout


def test_cli_fullmatch_mode():
    assert run_cli("--mode", "fullmatch", r"\d+", "123").returncode == 0
    assert run_cli("--mode", "fullmatch", r"\d+", "12a").returncode == 1
