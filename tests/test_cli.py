"""datamask-cli 命令行工具测试。"""

import io

import pytest

from datamask.cli import main


def run_cli(argv, capsys, stdin_text=None, monkeypatch=None):
    if stdin_text is not None:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin_text))
    code = main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_basic_search(capsys):
    code, out, _ = run_cli([r"\d{4}", "工单 1234 与 5678"], capsys)
    assert code == 0
    assert "count: 2" in out
    assert "span=(3, 7)" in out
    assert "'1234'" in out


def test_search_no_match_exit_code(capsys):
    code, out, _ = run_cli([r"\d+", "没有数字"], capsys)
    assert code == 1
    assert "count: 0" in out


def test_capture_groups_output(capsys):
    code, out, _ = run_cli([r"(?P<area>\d{3})-(\d{4})", "拨打 010-1234"], capsys)
    assert code == 0
    assert "groups: ('010', '1234')" in out
    assert "group 'area': '010'" in out


def test_findall_option(capsys):
    code, out, _ = run_cli([r"\d+", "a1b22c333", "--findall"], capsys)
    assert code == 0
    assert "'1'" in out and "'22'" in out and "'333'" in out


def test_ignore_case_option(capsys):
    code, out, _ = run_cli(["--ignore-case", "abc", "xxAbCxx"], capsys)
    assert code == 0
    assert "'AbC'" in out


def test_multiline_option(capsys):
    code, out, _ = run_cli(["--multiline", "^b", "a\nb\nc"], capsys)
    assert code == 0
    assert "count: 1" in out


def test_stdin_input(capsys, monkeypatch):
    code, out, _ = run_cli([r"\d+"], capsys,
                           stdin_text="编号 42 号", monkeypatch=monkeypatch)
    assert code == 0
    assert "'42'" in out


def test_file_option(capsys, tmp_path):
    f = tmp_path / "ticket.txt"
    f.write_text("联系电话 13812345678", encoding="utf-8")
    code, out, _ = run_cli([r"1[3-9]\d{9}", "--file", str(f)], capsys)
    assert code == 0
    assert "13812345678" in out


def test_file_not_found(capsys):
    code, _, err = run_cli(["x", "--file", "/nonexistent/path.txt"], capsys)
    assert code == 2
    assert "cannot read" in err


def test_mask_single_rule(capsys):
    code, out, _ = run_cli(["--mask", "mobile", "电话13812345678"], capsys)
    assert code == 0
    assert out.strip() == "电话138****5678"


def test_mask_all_rules(capsys):
    code, out, _ = run_cli(
        ["--mask", "all", "手机13812345678 邮箱bob@example.com"], capsys)
    assert code == 0
    assert out.strip() == "手机138****5678 邮箱b***@example.com"


def test_mask_multiple_rules_comma(capsys):
    code, out, _ = run_cli(
        ["--mask", "mobile,email", "手机13812345678 邮箱bob@example.com"],
        capsys)
    assert code == 0
    assert out.strip() == "手机138****5678 邮箱b***@example.com"


def test_mask_from_stdin(capsys, monkeypatch):
    code, out, _ = run_cli(["--mask", "idcard"], capsys,
                           stdin_text="证件 11010119900307123X",
                           monkeypatch=monkeypatch)
    assert code == 0
    assert out.strip() == "证件 110101********123X"


def test_mask_unknown_rule(capsys):
    code, _, err = run_cli(["--mask", "nope", "text"], capsys)
    assert code == 2
    assert "unknown rule" in err


def test_invalid_pattern_error(capsys):
    code, _, err = run_cli(["(unclosed", "text"], capsys)
    assert code == 2
    assert "unterminated group" in err
    assert "column" in err


def test_max_steps_option(capsys):
    code, _, err = run_cli(
        ["--max-steps", "10", "(a+)+$", "a" * 5000 + "b"], capsys)
    assert code == 2
    assert "step budget" in err
