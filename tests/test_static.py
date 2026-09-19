from helpers import http_request, parse_response, raw_request


def test_static_file_mime_and_contents(port):
    status, headers, body, *_ = http_request(port, "GET", "/style.css", b"")
    assert status == 200
    assert headers["content-type"] == "text/css; charset=utf-8"
    assert body == b"body {}"


def test_directory_default_index(port):
    status, headers, body, *_ = http_request(port, "GET", "/", b"")
    assert status == 200
    assert headers["content-type"] == "text/html; charset=utf-8"
    assert body == b"<h1>index</h1>"

    status, headers, body, *_ = http_request(port, "GET", "/sub/", b"")
    assert status == 200
    assert body == b"<h1>sub index</h1>"


def test_missing_static_file_404(port):
    status, headers, body, *_ = http_request(port, "GET", "/nope.txt", b"")
    assert status == 404
    assert b"404 Not Found" in body


def test_directory_without_index_returns_403(port):
    status, headers, body, *_ = http_request(port, "GET", "/private/", b"")
    assert status == 403
    assert b"403 Forbidden" in body


def test_static_head_has_correct_content_length_no_body(port):
    status, headers, body, *_ = http_request(port, "HEAD", "/style.css", b"")
    assert status == 200
    assert headers["content-length"] == str(len(b"body {}"))
    assert body == b""


def test_static_post_returns_405_allow(port):
    status, headers, body, *_ = http_request(port, "POST", "/style.css", b"")
    assert status == 405
    assert headers["allow"] == "GET, HEAD"


def test_dotdot_traversal_rejected(port):
    payload = (
        b"GET /../outside.txt HTTP/1.1\r\nHost: x\r\n\r\n"
    )
    status, *_ = parse_response(raw_request(port, payload))
    assert status == 404


def test_encoded_dotdot_traversal_rejected(port):
    variants = [
        b"/%2e%2e/outside.txt",
        b"/%2e%2e%2foutside.txt",
        b"/%252e%252e%252foutside.txt",
        b"/sub/..%2f..%2foutside.txt",
        b"/%5c..%5coutside.txt",
    ]
    for path in variants:
        payload = b"GET " + path + b" HTTP/1.1\r\nHost: x\r\n\r\n"
        status, *_ = parse_response(raw_request(port, payload))
        assert status == 404, path



def test_percent_encoded_dot_in_normal_file_is_allowed(port):
    status, headers, body, *_ = http_request(port, "GET", "/style%2Ecss", b"")
    assert status == 200
    assert body == b"body {}"
