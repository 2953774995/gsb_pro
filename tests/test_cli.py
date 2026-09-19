"""End-to-end tests for the tinytpl-cli command line tool."""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "tinytpl.cli"] + list(args),
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_cli_renders_template_with_json(tmp_path):
    tpl = tmp_path / "page.html"
    tpl.write_text("Hello {{ name }}, {{ n }} + 1 = {{ n + 1 }}", encoding="utf-8")
    data = tmp_path / "data.json"
    data.write_text(json.dumps({"name": "cli", "n": 4}), encoding="utf-8")

    result = run_cli(str(tpl), str(data))
    assert result.returncode == 0
    assert result.stdout == "Hello cli, 4 + 1 = 5\n"


def test_cli_escapes_html(tmp_path):
    tpl = tmp_path / "t.html"
    tpl.write_text("{{ x }}|{{ x | raw }}", encoding="utf-8")
    data = tmp_path / "d.json"
    data.write_text(json.dumps({"x": "<b>"}), encoding="utf-8")

    result = run_cli(str(tpl), str(data))
    assert result.returncode == 0
    assert result.stdout == "&lt;b&gt;|<b>\n"


def test_cli_template_error_exit_code(tmp_path):
    tpl = tmp_path / "bad.html"
    tpl.write_text("{% unknown %}", encoding="utf-8")
    data = tmp_path / "d.json"
    data.write_text("{}", encoding="utf-8")

    result = run_cli(str(tpl), str(data))
    assert result.returncode == 1
    assert "unknown tag" in result.stderr


def test_cli_strict_mode(tmp_path):
    tpl = tmp_path / "s.html"
    tpl.write_text("{{ missing }}", encoding="utf-8")
    data = tmp_path / "d.json"
    data.write_text("{}", encoding="utf-8")

    ok = run_cli(str(tpl), str(data))
    assert ok.returncode == 0
    assert ok.stdout == "\n"

    strict = run_cli(str(tpl), str(data), "--strict")
    assert strict.returncode == 1
    assert "undefined variable" in strict.stderr


def test_cli_bad_json(tmp_path):
    tpl = tmp_path / "t.html"
    tpl.write_text("x", encoding="utf-8")
    data = tmp_path / "d.json"
    data.write_text("not json", encoding="utf-8")

    result = run_cli(str(tpl), str(data))
    assert result.returncode == 2
