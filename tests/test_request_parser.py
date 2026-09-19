"""Direct parser tests against in-memory streams (no sockets)."""

import io

import pytest

from miniweb import Config
from miniweb.errors import RequestError
from miniweb.request import read_request


class FakeWriter:
    def __init__(self):
        self.buf = b""

    def write(self, data):
        self.buf += data

    def flush(self):
        pass


def parse(raw: bytes, config=None):
    reader = io.BytesIO(raw)
    return read_request(reader, FakeWriter(), config or Config())


def test_simple_get():
    req = parse(b"GET /a/b?x=1 HTTP/1.1\r\nHost: example\r\n\r\n")
    assert req.method == "GET"
    assert req.path == "/a/b"
    assert req.query_string == "x=1"
    assert req.version == "HTTP/1.1"
    assert req.get_header("HOST") == "example"
    assert req.keep_alive is True


def test_header_case_insensitive_and_duplicates_merged():
    req = parse(
        b"GET / HTTP/1.1\r\nHost: x\r\nX-Multi: a\r\nX-Multi: b\r\n\r\n"
    )
    assert req.headers["x-multi"] == "a, b"
    assert len([1 for n, _ in req.header_list if n == "x-multi"]) == 2


def test_body_by_content_length():
    req = parse(
        b"POST /x HTTP/1.1\r\nHost: h\r\nContent-Length: 5\r\n\r\nhello"
    )
    assert req.body == b"hello"


def test_short_body_raises():
    with pytest.raises(RequestError):
        parse(b"POST /x HTTP/1.1\r\nHost: h\r\nContent-Length: 9\r\n\r\nshort")


def test_invalid_content_length():
    with pytest.raises(RequestError):
        parse(b"POST /x HTTP/1.1\r\nHost: h\r\nContent-Length: -3\r\n\r\n")


def test_body_over_limit_413():
    cfg = Config(max_body_size=4)
    with pytest.raises(RequestError) as exc:
        parse(
            b"POST /x HTTP/1.1\r\nHost: h\r\nContent-Length: 10\r\n\r\n"
            b"0123456789",
            cfg,
        )
    assert exc.value.status == 413


def test_missing_host_11():
    with pytest.raises(RequestError):
        parse(b"GET / HTTP/1.1\r\nX: y\r\n\r\n")


def test_host_optional_10():
    req = parse(b"GET / HTTP/1.0\r\nX: y\r\n\r\n")
    assert req.keep_alive is False
    req2 = parse(
        b"GET / HTTP/1.0\r\nConnection: keep-alive\r\n\r\n"
    )
    assert req2.keep_alive is True


def test_connection_close_11():
    req = parse(
        b"GET / HTTP/1.1\r\nHost: h\r\nConnection: close\r\n\r\n"
    )
    assert req.keep_alive is False


@pytest.mark.parametrize(
    "raw",
    [
        b"GET / HTTP/1.1\r\nHost: h\r\nContent-Length: 0\r\nContent-Length: 1\r\n\r\n",
        b"GET / HTTP/1.1\r\nHost: a\r\nHost: b\r\n\r\n",
        b"GET / HTTP/1.1\r\nHost: h\r\nBad-Header\r\n\r\n",
        b"GET / HTTP/1.1\r\nHost: h\r\n : v\r\n\r\n",
        b"GOT / HTTP/1.1\r\nHost: h\r\n\r\n",
        b"GET / HTTP/2.0\r\nHost: h\r\n\r\n",
        b"GET relative HTTP/1.1\r\nHost: h\r\n\r\n",
    ],
)
def test_malformed(raw):
    with pytest.raises(RequestError):
        parse(raw)


def test_chunked_body():
    raw = (
        b"POST /x HTTP/1.1\r\nHost: h\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n"
        b"5\r\nhello\r\n2\r\n!!\r\n0\r\n\r\n"
    )
    req = parse(raw)
    assert req.body == b"hello!!"


def test_chunked_bad_size():
    raw = (
        b"POST /x HTTP/1.1\r\nHost: h\r\n"
        b"Transfer-Encoding: chunked\r\n\r\nzz\r\n"
    )
    with pytest.raises(RequestError):
        parse(raw)


def test_chunked_and_length_conflict():
    with pytest.raises(RequestError):
        parse(
            b"POST /x HTTP/1.1\r\nHost: h\r\n"
            b"Transfer-Encoding: chunked\r\nContent-Length: 3\r\n\r\n"
        )


def test_query_multimap():
    req = parse(b"GET /s?a=1&a=2&b= HTTP/1.1\r\nHost: h\r\n\r\n")
    assert req.query == {"a": ["1", "2"], "b": [""]}


def test_form_helpers():
    req = parse(
        b"POST /x HTTP/1.1\r\nHost: h\r\n"
        b"Content-Type: application/x-www-form-urlencoded\r\n"
        b"Content-Length: 14\r\n\r\na=1&b=hi+there"
    )
    assert req.form == {"a": ["1"], "b": ["hi there"]}
    assert req.form_value("a") == "1"
    assert req.form_value("missing", "d") == "d"


def test_form_wrong_content_type_empty():
    req = parse(
        b"POST /x HTTP/1.1\r\nHost: h\r\nContent-Type: text/plain\r\n"
        b"Content-Length: 3\r\n\r\na=1"
    )
    assert req.form == {}


def test_json_helper():
    req = parse(
        b"POST /x HTTP/1.1\r\nHost: h\r\nContent-Type: application/json\r\n"
        b"Content-Length: 8\r\n\r\n{\"a\": 1}"
    )
    assert req.json == {"a": 1}


def test_json_helper_bad():
    req = parse(
        b"POST /x HTTP/1.1\r\nHost: h\r\nContent-Type: application/json\r\n"
        b"Content-Length: 2\r\n\r\n{}"
    )
    assert req.json == {}
    bad = parse(
        b"POST /x HTTP/1.1\r\nHost: h\r\nContent-Type: application/json\r\n"
        b"Content-Length: 3\r\n\r\nxxx"
    )
    with pytest.raises(RequestError):
        bad.json


def test_100_continue_written():
    writer = FakeWriter()
    reader = io.BytesIO(
        b"POST /x HTTP/1.1\r\nHost: h\r\nContent-Length: 2\r\n"
        b"Expect: 100-continue\r\n\r\nhi"
    )
    req = read_request(reader, writer, Config())
    assert req.body == b"hi"
    assert writer.buf.startswith(b"HTTP/1.1 100 Continue")


def test_no_100_continue_on_http10():
    writer = FakeWriter()
    reader = io.BytesIO(
        b"POST /x HTTP/1.0\r\nContent-Length: 2\r\n"
        b"Expect: 100-continue\r\n\r\nhi"
    )
    read_request(reader, writer, Config())
    assert writer.buf == b""


def test_ows_trimmed():
    req = parse(b"GET / HTTP/1.1\r\nHost:    spaced   \r\n\r\n")
    assert req.headers["host"] == "spaced"
