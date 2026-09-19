"""End-to-end tests for the rex-cli command-line tool."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args, stdin=None):
    return subprocess.run(
        [sys.executable, "-m", "rex", *args],
        capture_output=True, text=True, input=stdin, cwd=str(ROOT),
    )


def test_basic_search_with_groups():
    r = run_cli(r"(\w+)@(\w+)", "mail bob@corp now")
    assert r.returncode == 0, r.stderr
    assert "match 1: span=(5, 13)" in r.stdout
    assert "text='bob@corp'" in r.stdout
    assert "group 1: 'bob'" in r.stdout
    assert "group 2: 'corp'" in r.stdout
    assert "1 match(es) found" in r.stdout


def test_multiple_matches_counted():
    r = run_cli(r"\d+", "a1b22c333")
    assert r.returncode == 0
    assert "3 match(es) found" in r.stdout
    assert "span=(1, 2)" in r.stdout
    assert "span=(3, 5)" in r.stdout


def test_no_match():
    r = run_cli("zzz", "abc")
    assert r.returncode == 0
    assert "0 match(es) found" in r.stdout


def test_stdin_input():
    r = run_cli(r"\d+", stdin="x42y")
    assert r.returncode == 0
    assert "text='42'" in r.stdout


def test_findall_option():
    r = run_cli("--findall", r"(\d)(\d)", "12 34")
    assert r.returncode == 0
    assert "('1', '2')" in r.stdout
    assert "('3', '4')" in r.stdout
    assert "2 match(es)" in r.stdout


def test_ignore_case_option():
    r = run_cli("-i", "hello", "say HELLO")
    assert r.returncode == 0
    assert "text='HELLO'" in r.stdout
    r = run_cli("--ignore-case", "hello", "say HELLO")
    assert "1 match(es) found" in r.stdout


def test_multiline_option():
    r = run_cli("-m", "^b", "a\nb")
    assert r.returncode == 0
    assert "1 match(es) found" in r.stdout
    r = run_cli("^b", "a\nb")
    assert "0 match(es) found" in r.stdout


def test_file_option(tmp_path):
    f = tmp_path / "data.txt"
    f.write_text("one\ntwo\nthree\n")
    r = run_cli("--file", str(f), r"^\w+", "-m")
    assert r.returncode == 0
    assert "3 match(es) found" in r.stdout


def test_named_group_output():
    r = run_cli(r"(?P<word>\w+)!", "hey!")
    assert r.returncode == 0
    assert "group word: 'hey'" in r.stdout


def test_invalid_pattern_exit_code():
    r = run_cli("(unclosed", "text")
    assert r.returncode == 2
    assert "invalid pattern" in r.stderr
    assert "column" in r.stderr


def test_timeout_exit_code():
    r = run_cli("(a+)+$", "a" * 25 + "b", "--max-steps", "50000")
    assert r.returncode == 3
    assert "step limit" in r.stderr


def test_missing_file():
    r = run_cli("--file", "/nonexistent/path.txt", "x")
    assert r.returncode == 2
