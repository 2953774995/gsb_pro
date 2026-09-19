from helpers import http_request, parse_response, raw_request


def test_internal_exception_becomes_500_without_traceback(port):
    status, headers, body, reason, version = http_request(port, "GET", "/boom", b"")
    assert status == 500
    assert reason == "Internal Server Error"
    assert b"RuntimeError" not in body
    assert b"Traceback" not in body
    assert b"500 Internal Server Error" in body
    assert headers["content-type"] == "text/html; charset=utf-8"


def test_internal_post_exception_becomes_500(port):
    status, *_ = http_request(
        port, "POST", "/boom", b"x", {"Content-Type": "text/plain"}
    )
    assert status == 500


def test_all_core_error_status_pages_are_html(port):
    # 400/404/405/500 exercised through practical server paths.
    checks = [
        (b"GARBAGE\r\n\r\n", 400),
        (b"GET /missing HTTP/1.1\r\nHost: x\r\n\r\n", 404),
        (b"DELETE /hello HTTP/1.1\r\nHost: x\r\n\r\n", 405),
    ]
    for payload, expected in checks:
        status, headers, body, *_ = parse_response(raw_request(port, payload))
        assert status == expected
        assert headers["content-type"] == "text/html; charset=utf-8"
        assert int(headers["content-length"]) == len(body)


def test_not_found_has_core_response_headers(port):
    status, headers, *_ = http_request(port, "GET", "/missing", b"")
    for header in ("content-type", "content-length", "connection", "server", "date"):
        assert header in headers
