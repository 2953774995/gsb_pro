from helpers import parse_response, raw_request


def test_malformed_request_line_returns_400(port):
    data = raw_request(port, b"GET /bad\r\nHost: localhost\r\n\r\n")
    status, headers, body, reason, version = parse_response(data)
    assert status == 400
    assert reason == "Bad Request"
    assert b"400 Bad Request" in body
    assert headers["connection"] == "close"


def test_bad_http_version_returns_400(port):
    data = raw_request(port, b"GET / HTTP/2.0\r\nHost: localhost\r\n\r\n")
    status, *_ = parse_response(data)
    assert status == 400


def test_http_11_missing_host_is_400(port):
    data = raw_request(port, b"GET /hello HTTP/1.1\r\n\r\n")
    status, *_ = parse_response(data)
    assert status == 400


def test_http_10_without_host_accepted(port):
    data = raw_request(
        port, b"GET /hello HTTP/1.0\r\nConnection: keep-alive\r\n\r\n"
    )
    status, headers, *_ = parse_response(data)
    assert status == 200
    assert headers["server"].lower() == "miniweb"


def test_oversized_header_returns_400(port):
    long_value = "x" * 9000
    payload = (
        f"GET /hello HTTP/1.1\r\nHost: localhost\r\nX-Big: {long_value}\r\n\r\n"
    ).encode()
    data = raw_request(port, payload)
    status, headers, body, *_ = parse_response(data)
    assert status == 400
    assert b"too long" in body.lower() or b"400 Bad Request" in body
    assert headers["connection"] == "close"


def test_oversized_request_line_returns_400(port):
    payload = (
        "GET /" + ("x" * 9000) + " HTTP/1.1\r\nHost: localhost\r\n\r\n"
    ).encode()
    data = raw_request(port, payload)
    status, *_ = parse_response(data)
    assert status == 400


def test_malformed_header_line_returns_400(port):
    data = raw_request(
        port, b"GET /hello HTTP/1.1\r\nHost localhost\r\n\r\n"
    )
    status, *_ = parse_response(data)
    assert status == 400


def test_invalid_method_returns_400(port):
    data = raw_request(port, b"GE T /hello HTTP/1.1\r\nHost: x\r\n\r\n")
    status, *_ = parse_response(data)
    assert status == 400


def test_invalid_content_length_returns_400(port):
    data = raw_request(
        port,
        b"POST /form HTTP/1.1\r\nHost: x\r\n"
        b"Content-Type: application/x-www-form-urlencoded\r\n"
        b"Content-Length: abc\r\n\r\n",
    )
    status, *_ = parse_response(data)
    assert status == 400


def test_content_length_body_short_returns_400(port):
    data = raw_request(
        port,
        b"POST /form HTTP/1.1\r\nHost: x\r\n"
        b"Content-Type: application/x-www-form-urlencoded\r\n"
        b"Content-Length: 5\r\n\r\nabc",
    )
    status, headers, body, *_ = parse_response(data)
    assert status == 400
    assert headers["connection"] == "close"
    assert b"400 Bad Request" in body


def test_control_character_in_header_returns_400(port):
    data = raw_request(
        port, b"GET /hello HTTP/1.1\r\nHost: x\r\nX-Bad: abc\x00def\r\n\r\n"
    )
    status, *_ = parse_response(data)
    assert status == 400


def test_oversized_declared_body_returns_413(port):
    data = raw_request(
        port,
        b"POST /form HTTP/1.1\r\nHost: x\r\n"
        b"Content-Length: 1073741824\r\nContent-Type: text/plain\r\n\r\n",
    )
    status, headers, body, *_ = parse_response(data)
    assert status == 413
    assert headers["connection"] == "close"
    assert b"413 Payload Too Large" in body


def test_invalid_utf8_percent_path_returns_400(port):
    data = raw_request(
        port, b"GET /%ff HTTP/1.1\r\nHost: localhost\r\n\r\n"
    )
    status, *_ = parse_response(data)
    assert status == 400
