"""Integration tests: routing, method dispatch, static files, error pages."""

import json

from helpers import request, raw_exchange


def test_static_index_page(env):
    status, headers, body = request(env.connect, "GET", "/")
    assert status == 200
    assert headers["content-type"].startswith("text/html")
    assert b"<h1>gwadmin</h1>" in body
    assert headers["server"].startswith("gwadmin/")
    assert "date" in headers
    assert headers["connection"] == "keep-alive"


def test_static_mime_types(env):
    cases = [
        ("/style.css", "text/css"),
        ("/app.js", "application/javascript"),
        ("/data.json", "application/json"),
        ("/notes.txt", "text/plain"),
        ("/index.html", "text/html"),
    ]
    for path, mime in cases:
        status, headers, _ = request(env.connect, "GET", path)
        assert status == 200, path
        assert headers["content-type"].startswith(mime), path


def test_static_subdirectory_index(env):
    status, _, body = request(env.connect, "GET", "/sub/")
    assert status == 200
    assert b"<h1>sub</h1>" in body


def test_static_directory_without_index_is_403(env):
    status, _, body = request(env.connect, "GET", "/emptydir/")
    assert status == 403
    assert b"403" in body


def test_static_missing_file_is_404(env):
    status, headers, body = request(env.connect, "GET", "/nope.txt")
    assert status == 404
    assert headers["content-type"].startswith("text/html")
    assert b"404" in body


def test_directory_traversal_rejected(env):
    # Encoded and plain traversal attempts must never escape the root.
    for path in ("/../gwadmin", "/..%2f..%2fetc/passwd", "/%2e%2e/%2e%2e/x",
                 "/sub/../../secret", "/..%2Findex.html", "/..",
                 "/%2e%2e%2f%2e%2e%2fetc%2fpasswd"):
        status, _, _ = request(env.connect, "GET", path)
        assert status == 404, path


def test_file_outside_root_not_served(env, www_root):
    secret = www_root.parent / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")
    status, _, body = request(env.connect, "GET", "/../secret.txt")
    assert status == 404
    assert b"top secret" not in body


def test_head_request_headers_only(env):
    status, headers, body = request(env.connect, "HEAD", "/index.html")
    assert status == 200
    assert body == b""
    _, _, get_body = request(env.connect, "GET", "/index.html")
    assert headers["content-length"] == str(len(get_body))


def test_head_on_api_status(env):
    status, headers, body = request(env.connect, "HEAD", "/api/status")
    assert status == 200
    assert body == b""
    assert int(headers["content-length"]) > 0


def test_method_not_allowed_has_allow_header(env):
    status, headers, body = request(env.connect, "POST", "/api/status",
                                    headers={"Content-Length": "0"})
    assert status == 405
    assert "GET" in headers["allow"]
    assert b"405" in body


def test_unregistered_path_is_404(env):
    status, _, _ = request(env.connect, "GET", "/api/nonexistent")
    assert status == 404


def test_post_to_static_is_405(env):
    status, headers, _ = request(env.connect, "POST", "/index.html",
                                 headers={"Content-Length": "0"})
    assert status == 405
    assert "GET" in headers["allow"]


def test_error_page_has_no_stack_trace(env):
    _, _, body = request(env.connect, "GET", "/missing")
    assert b"Traceback" not in body
    assert b'File "' not in body


def test_path_params_route(env):
    status, _, body = request(env.connect, "GET", "/api/devices/gw-07")
    assert status == 200
    assert json.loads(body)["id"] == "gw-07"


def test_query_string_routing(env):
    status, _, body = request(env.connect, "GET", "/api/status?verbose=1")
    assert status == 200
    assert json.loads(body)["status"] == "ok"


def test_connection_close_header(env):
    status, headers, _ = request(env.connect, "GET", "/",
                                 headers={"Connection": "close"})
    assert status == 200
    assert headers["connection"] == "close"


def test_http_1_0_defaults_to_close(env):
    _, headers, _ = request(env.connect, "GET", "/", version="HTTP/1.0")
    assert headers["connection"] == "close"


def test_malformed_request_gets_400(env):
    raw = raw_exchange(env.connect, b"GARBAGE LINE\r\n\r\n")
    assert raw.startswith(b"HTTP/1.1 400")


def test_bad_version_gets_400(env):
    raw = raw_exchange(env.connect, b"GET / HTTP/9.9\r\nHost: x\r\n\r\n")
    assert raw.startswith(b"HTTP/1.1 400")


def test_missing_host_gets_400(env):
    raw = raw_exchange(env.connect, b"GET / HTTP/1.1\r\n\r\n")
    assert raw.startswith(b"HTTP/1.1 400")


def test_oversized_header_gets_400(env):
    payload = (b"GET / HTTP/1.1\r\nHost: x\r\nX-Big: " + b"A" * 9000 +
               b"\r\n\r\n")
    raw = raw_exchange(env.connect, payload)
    assert raw.startswith(b"HTTP/1.1 400")


def test_bad_content_length_gets_400(env):
    raw = raw_exchange(
        env.connect,
        b"POST /api/config HTTP/1.1\r\nHost: x\r\nContent-Length: zz\r\n\r\n")
    assert raw.startswith(b"HTTP/1.1 400")


def test_incomplete_body_gets_400(env):
    raw = raw_exchange(
        env.connect,
        b"POST /api/config HTTP/1.1\r\nHost: x\r\nContent-Length: 50\r\n\r\n"
        b"short",
        shutdown_write=True)
    assert raw.startswith(b"HTTP/1.1 400")


def test_malformed_requests_do_not_kill_server(env):
    for payload in (b"\x00\x01\x02\r\n\r\n", b"\xff\xfe\xfd\r\n\r\n",
                    b"GET\r\n\r\n", b"\r\n\r\n\r\n"):
        raw_exchange(env.connect, payload)
    status, _, _ = request(env.connect, "GET", "/api/status")
    assert status == 200
