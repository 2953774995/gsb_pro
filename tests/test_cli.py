"""命令行工具 tinytpl-cli。"""

import json

from tinytpl.cli import main


def test_cli_basic(tmp_path, capsys):
    tpl = tmp_path / "page.html"
    tpl.write_text("Hello {{ name }}!", encoding="utf-8")
    data = tmp_path / "data.json"
    data.write_text(json.dumps({"name": "CLI"}), encoding="utf-8")
    assert main([str(tpl), str(data)]) == 0
    out = capsys.readouterr().out
    assert out == "Hello CLI!\n"


def test_cli_with_extends_and_include(tmp_path, capsys):
    (tmp_path / "base.html").write_text(
        "<title>{% block t %}?{% endblock %}</title>"
        "{% include \"foot.html\" %}", encoding="utf-8")
    (tmp_path / "foot.html").write_text("(c) {{ year }}", encoding="utf-8")
    (tmp_path / "page.html").write_text(
        "{% extends \"base.html\" %}{% block t %}{{ title }}{% endblock %}",
        encoding="utf-8")
    data = tmp_path / "d.json"
    data.write_text(json.dumps({"title": "T", "year": 2026}),
                    encoding="utf-8")
    assert main([str(tmp_path / "page.html"), str(data)]) == 0
    assert capsys.readouterr().out == "<title>T</title>(c) 2026\n"


def test_cli_template_error_exit_code(tmp_path, capsys):
    tpl = tmp_path / "bad.html"
    tpl.write_text("{% if x %}", encoding="utf-8")
    data = tmp_path / "d.json"
    data.write_text("{}", encoding="utf-8")
    assert main([str(tpl), str(data)]) == 1
    assert "tinytpl-cli" in capsys.readouterr().err


def test_cli_bad_json_exit_code(tmp_path, capsys):
    tpl = tmp_path / "t.html"
    tpl.write_text("x", encoding="utf-8")
    data = tmp_path / "d.json"
    data.write_text("{not json", encoding="utf-8")
    assert main([str(tpl), str(data)]) == 2


def test_cli_missing_data_file(tmp_path, capsys):
    tpl = tmp_path / "t.html"
    tpl.write_text("x", encoding="utf-8")
    assert main([str(tpl), str(tmp_path / "nope.json")]) == 2


def test_cli_strict_mode(tmp_path, capsys):
    tpl = tmp_path / "t.html"
    tpl.write_text("{{ missing }}", encoding="utf-8")
    data = tmp_path / "d.json"
    data.write_text("{}", encoding="utf-8")
    assert main([str(tpl), str(data)]) == 0  # 默认不严格
    assert main([str(tpl), str(data), "--strict"]) == 1
