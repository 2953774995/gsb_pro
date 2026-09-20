import threading
import urllib.request
from http.server import ThreadingHTTPServer

from mdsite.cli import main


def test_cli_missing_directory_error_without_traceback(tmp_path, capsys):
    code = main(["build", str(tmp_path / "missing"), str(tmp_path / "site")])
    captured = capsys.readouterr()
    assert code == 2
    assert "mdsite: 错误: 输入目录不存在" in captured.err
    assert "Traceback" not in captured.err


def test_cli_build_success(tmp_path, capsys):
    src = tmp_path / "docs"
    src.mkdir()
    (src / "index.md").write_text("# Hello\n", encoding="utf-8")
    out = tmp_path / "site"
    code = main(["build", str(src), str(out), "--theme", "dark"])
    captured = capsys.readouterr()
    assert code == 0
    assert "构建完成: 1 个页面" in captured.out
    assert (out / "assets" / "style.css").read_text(encoding="utf-8").startswith(":root")


def test_cli_serve_serves_built_directory(tmp_path, monkeypatch, capsys):
    out = tmp_path / "site"
    out.mkdir()
    (out / "index.html").write_text("<h1>Serve</h1>", encoding="utf-8")

    seen = {}

    class FakeServer:
        def __init__(self, address, handler):
            seen["address"] = address
            seen["handler"] = handler

        def serve_forever(self):
            seen["served"] = True

        def server_close(self):
            seen["closed"] = True

    monkeypatch.setattr("mdsite.cli.ThreadingHTTPServer", FakeServer)
    code = main(["serve", str(out), "--port", "9123"])
    captured = capsys.readouterr()
    assert code == 0
    assert seen["address"] == ("127.0.0.1", 9123)
    assert seen["served"] is True
    assert seen["closed"] is True
    assert "http://127.0.0.1:9123/" in captured.out


def test_cli_serve_missing_directory_error(tmp_path, capsys):
    code = main(["serve", str(tmp_path / "missing")])
    captured = capsys.readouterr()
    assert code == 2
    assert "目录不存在" in captured.err
    assert "Traceback" not in captured.err
