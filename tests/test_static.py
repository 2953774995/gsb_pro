"""Static file serving: MIME, index page, 404/403, traversal protection."""

import os

import pytest

STATIC_ROOT = os.path.join(os.path.dirname(__file__), "static")


def test_index_html_for_directory(client):
    resp = client.request("GET", "/")
    assert resp.status == 200
    assert "text/html" in resp.headers["content-type"]
    assert b"Hello from miniweb" in resp.body


def test_explicit_html(client):
    resp = client.request("GET", "/index.html")
    assert resp.status == 200
    assert "text/html" in resp.headers["content-type"]
    assert int(resp.headers["content-length"]) == len(resp.body)


def test_css_mime(client):
    resp = client.request("GET", "/style.css")
    assert resp.status == 200
    assert resp.headers["content-type"].startswith("text/css")
    assert b"color" in resp.body


def test_js_mime(client):
    resp = client.request("GET", "/app.js")
    assert "javascript" in resp.headers["content-type"]


def test_png_binary_mime(client):
    resp = client.request("GET", "/pixel.png")
    assert resp.status == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.body.startswith(b"\x89PNG\r\n")


def test_nested_file(client):
    resp = client.request("GET", "/sub/page.txt")
    assert resp.status == 200
    assert "text/plain" in resp.headers["content-type"]
    assert resp.body == b"sub page\n"


def test_head_static(client):
    resp = client.request("HEAD", "/style.css")
    assert resp.status == 200
    assert resp.body == b""
    assert int(resp.headers["content-length"]) == os.path.getsize(
        os.path.join(STATIC_ROOT, "style.css")
    )


def test_missing_file_404(client):
    resp = client.request("GET", "/does-not-exist.txt")
    assert resp.status == 404


def test_directory_without_index_403(client):
    resp = client.request("GET", "/noindex/")
    assert resp.status == 403


def test_directory_without_slash_redirects(client):
    resp = client.request("GET", "/sub")
    assert resp.status == 301
    assert resp.headers["location"] == "/sub/"


@pytest.mark.parametrize(
    "evil",
    [
        "/../etc/passwd",
        "/sub/../../etc/passwd",
        "/%2e%2e/etc/passwd",
        "/%2e%2e%2fetc%2fpasswd",
        "/sub/..%2f..%2fetc/passwd",
        "/..%252f..%252fetc/passwd",
        "/%c0%ae%c0%ae/etc/passwd",
        "/sub\\..\\..\\etc\\passwd",
        "/....//....//etc/passwd",
    ],
)
def test_directory_traversal_rejected(client, evil):
    resp = client.request("GET", evil)
    assert resp.status in (400, 404), evil
    assert b"root:" not in resp.body


def test_encoded_normal_path_still_works(client):
    resp = client.request("GET", "/sub/%70age.txt")
    assert resp.status == 200
    assert resp.body == b"sub page\n"


def test_url_encoded_spaces(client):
    name = "a file.txt"
    with open(os.path.join(STATIC_ROOT, name), "wb") as handle:
        handle.write(b"space")
    try:
        resp = client.request("GET", "/a%20file.txt")
        assert resp.status == 200
        assert resp.body == b"space"
    finally:
        os.remove(os.path.join(STATIC_ROOT, name))


def test_symlink_escape_rejected(tmp_path, server_factory, make_client):
    outside = tmp_path / "secret.txt"
    outside.write_text("secret data")
    web_root = tmp_path / "root"
    web_root.mkdir()
    try:
        os.symlink(outside, web_root / "link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported on this platform")
    from miniweb import Config

    srv = server_factory(
        config=Config(host="127.0.0.1", port=0, static_root=str(web_root))
    )
    client = make_client(srv)
    resp = client.request("GET", "/link.txt")
    assert resp.status == 404
    assert b"secret" not in resp.body


def test_unknown_extension_is_octet_stream(tmp_path, server_factory, make_client):
    web_root = tmp_path / "root"
    web_root.mkdir()
    (web_root / "data.xyzq").write_bytes(b"\x00\x01")
    from miniweb import Config

    srv = server_factory(
        config=Config(host="127.0.0.1", port=0, static_root=str(web_root))
    )
    client = make_client(srv)
    resp = client.request("GET", "/data.xyzq")
    assert resp.status == 200
    assert resp.headers["content-type"] == "application/octet-stream"
