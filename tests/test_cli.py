"""End-to-end tests for the rex-cli command line entry point."""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = [sys.executable, os.path.join(ROOT, "rex-cli")]


def run_cli(*args, input_text=None):
    return subprocess.run(
        CLI + list(args),
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=ROOT,
        check=False,
    )


def test_basic_search_reports_position_count_and_groups():
    result = run_cli(r"(\w+)@(\w+\.\w+)", "mail bob@example.com and sue@x.org")
    assert result.returncode == 0
    assert "match at 5-20" in result.stdout
    assert "group 1: 'bob'" in result.stdout
    assert "group 2: 'example.com'" in result.stdout
    assert "match at 25-34" in result.stdout
    assert "matches: 2" in result.stdout


def test_findall_mode():
    result = run_cli("--findall", r"(\d+):(\w+)", "1:ab 22:cd")
    assert result.returncode == 0
    lines = result.stdout.splitlines()
    assert lines[0] == "1\tab"
    assert lines[1] == "22\tcd"
    assert "matches: 2" in result.stderr


def test_ignore_case_flag():
    result = run_cli("-i", "dog", "DOG dog Dog", "--findall")
    assert result.stdout.splitlines() == ["DOG", "dog", "Dog"]


def test_multiline_flag():
    result = run_cli("--multiline", "--count", "^foo", input_text="foo\nbar\nfoo\n")
    assert result.stdout.strip() == "2"


def test_file_option(tmp_path):
    data = tmp_path / "sample.txt"
    data.write_text("abc 123 def 456\n", encoding="utf-8")
    result = run_cli(r"\d+", "--file", str(data), "--findall")
    assert result.stdout.splitlines() == ["123", "456"]


def test_pattern_on_stdin_first_line():
    result = run_cli(input_text=r"\d+" + "\n" + "a 1 b 22\n")
    assert result.returncode == 0
    assert "matches: 2" in result.stdout


def test_invalid_pattern_exit_code_and_message():
    result = run_cli("a(", "abc")
    assert result.returncode == 2
    assert "invalid pattern" in result.stderr
    assert "column" in result.stderr


def test_named_groups_labelled():
    result = run_cli(r"(?P<area>\d{3})-(\d{4})", "call 555-1234")
    assert "group <area>: '555'" in result.stdout
    assert "group 1: '1234'" in result.stdout


def test_no_matches_is_not_an_error():
    result = run_cli("zzz", "abc")
    assert result.returncode == 0
    assert "no matches" in result.stderr


def test_module_invocation():
    result = subprocess.run(
        [sys.executable, "-m", "rex", "abc", "xabcx"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0
    assert "match at 1-4" in result.stdout
