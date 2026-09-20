"""CLI 层测试：build / serve 的返回码与错误提示。"""
import threading
import urllib.request

import pytest

from mdsite.cli import main


@pytest.fixture
def docs(tmp_path):
    src = tmp_path / "docs"
    src.mkdir()
    (src / "index.md").write_text("# 首页\n\n## 节\n", encoding="utf-8")
    return src


def test_cli_build_ok(docs, tmp_path, capsys):
    rc = main(["build", str(docs), str(tmp_path / "out")])
    assert rc == 0
    assert "构建完成" in capsys.readouterr().out


def test_cli_build_bad_src(tmp_path, capsys):
    rc = main(["build", str(tmp_path / "nope"), str(tmp_path / "out")])
    assert rc == 2
    err = capsys.readouterr().err
    assert "错误" in err and "不存在" in err
    assert "Traceback" not in err


def test_cli_build_bad_theme(docs, tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["build", str(docs), str(tmp_path / "out"), "--theme", "bogus"])
    assert exc.value.code == 2  # argparse 自己报错退出


def test_cli_serve_missing_dir(tmp_path, capsys):
    rc = main(["serve", str(tmp_path / "nope")])
    assert rc == 2
    assert "不存在" in capsys.readouterr().err


def test_cli_serve_and_fetch(docs, tmp_path):
    out = tmp_path / "out"
    main(["build", str(docs), str(out)])
    # 起服务线程，抓一个页面再停掉
    import functools
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(out))
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    except PermissionError:
        pytest.skip("当前环境不允许绑定端口")
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:%d/index.html" % port, timeout=5
        ) as resp:
            body = resp.read().decode("utf-8")
        assert resp.status == 200
        assert "<h1" in body and "首页" in body
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)
