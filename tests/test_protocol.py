import socket

import pytest

from gwadmin.errors import BadRequest, PayloadTooLarge
from gwadmin.protocol import build_response, read_request
from gwadmin.request import Request
from gwadmin.headers import Headers


class FakeConn:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.peer = ("127.0.0.1", 12345)

    def recv(self, size):
        chunk = self.data[self.pos:self.pos + size]
        self.pos += len(chunk)
        return chunk


def parse(data, **kwargs):
    return read_request(FakeConn(data), **kwargs)


def base_request(body=b"", extra_headers=b""):
    if body:
        extra_headers += f"Content-Length: {len(body)}\r\n".encode()
    return (
        b"POST /api/config?a=1&a=2&x=hello%20world HTTP/1.1\r\nHost: gw\r\n"
        + extra_headers
        + b"\r\n"
        + body
    )


def test_parse_valid_request_query_case_insensitive_and_duplicate_headers():
    req = parse(base_request(b"", b"X-Test: one\r\nX-Test: two\r\n"))
    assert req.method == "POST"
    assert req.query == {"a": ["1", "2"], "x": "hello world"}
    assert req.headers.get("x-test") == "one, two"


def test_bad_request_line_version_and_method():
    with pytest.raises(BadRequest):
        parse(b"BREW / HTTP/1.1\r\nHost: x\r\n\r\n")
    with pytest.raises(BadRequest):
        parse(b"GET / HTTP/2.0\r\nHost: x\r\n\r\n")


def test_missing_host_is_400():
    with pytest.raises(BadRequest, match="Host"):
        parse(b"GET / HTTP/1.1\r\n\r\n")


def test_oversized_header_is_400():
    request = b"GET / HTTP/1.1\r\nHost: x\r\nX-Big: " + b"a" * 9000 + b"\r\n\r\n"
    with pytest.raises(BadRequest, match="too long"):
        parse(request, header_limit=8192)


def test_invalid_header_format_and_duplicate_content_length():
    with pytest.raises(BadRequest):
        parse(b"GET / HTTP/1.1\r\nHost: x\r\nBad-Header\r\n\r\n")
    with pytest.raises(BadRequest):
        parse(
            b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 1\r\n"
            b"Content-Length: 1\r\n\r\nx"
        )


def test_content_length_invalid_and_body_truncated():
    with pytest.raises(BadRequest):
        parse(b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: abc\r\n\r\n")
    with pytest.raises(BadRequest, match="complete request body"):
        parse(b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 5\r\n\r\nabc")


def test_body_limit_raises_413_type():
    with pytest.raises(PayloadTooLarge):
        parse(base_request(b"x" * 10), body_limit=4)


def test_head_response_has_no_body_but_correct_content_length():
    headers = Headers()
    req = Request("HEAD", "/", "/", {}, "HTTP/1.1", headers)
    raw = build_response(req, 200, {"X-K": "v"}, b"abcdef", True)
    assert raw.endswith(b"\r\n\r\n")
    assert b"content-length: 6" in raw.lower()
    assert b"abcdef" not in raw
    assert b"server:" in raw.lower()
    assert b"date:" in raw.lower()


@pytest.mark.parametrize("status", [200, 301, 302, 400, 404, 405, 413, 500])
def test_all_required_status_lines_and_default_headers(status):
    req = Request("GET", "/", "/", {}, "HTTP/1.1", Headers())
    raw = build_response(
        req,
        status,
        {"Location": "/elsewhere"} if status in (301, 302) else None,
        b"x",
        False,
    ).lower()
    assert f"http/1.1 {status}".encode() in raw
    for required in [b"content-type:", b"content-length: 1", b"connection: close", b"server:", b"date:"]:
        assert required in raw
