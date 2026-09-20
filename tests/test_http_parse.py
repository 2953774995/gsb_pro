"""Unit tests for the hand-written HTTP/1.1 request parser."""

import io

import pytest

from gwadmin.http import (HTTPError, Headers, Request, read_request,
                          serialize_response, MAX_HEAD_BYTES)


def parse(raw):
    return read_request(io.BytesIO(raw))


def test_parse_basic_get():
    req = parse(b"GET /index.html?a=1&b=2 HTTP/1.1\r\n"
                b"Host: example.local\r\n"
                b"User-Agent: test\r\n\r\n")
    assert req.method == "GET"
    assert req.path == "/index.html"
    assert req.version == "HTTP/1.1"
    assert req.query == {"a": ["1"], "b": ["2"]}
    assert req.headers.get("host") == "example.local"
    assert req.headers.get("HOST") == "example.local"
    assert req.body == b""


def test_headers_case_insensitive_and_duplicates_merged():
    req = parse(b"GET / HTTP/1.1\r\nHost: x\r\n"
                b"X-Thing: one\r\nx-thing: two\r\nX-THING: three\r\n\r\n")
    assert req.headers.get("X-Thing") == "one, two, three"


def test_query_repeated_keys_aggregate():
    req = parse(b"GET /?k=1&k=2&k=3&empty=&flag HTTP/1.1\r\nHost: x\r\n\r\n")
    assert req.query["k"] == ["1", "2", "3"]
    assert req.query["empty"] == [""]
    assert req.query["flag"] == [""]


def test_query_percent_decoding():
    req = parse(b"GET /?name=hello+world&sym=%26%3D HTTP/1.1\r\n"
                b"Host: x\r\n\r\n")
    assert req.query["name"] == ["hello world"]
    assert req.query["sym"] == ["&="]


def test_post_body_read_exactly_content_length():
    body = b"x=1&y=2"
    req = parse(b"POST /submit HTTP/1.1\r\nHost: x\r\n"
                b"Content-Length: %d\r\n\r\n%sEXTRA" % (len(body), body))
    assert req.body == body  # trailing bytes are not consumed


def test_content_length_non_numeric_rejected():
    with pytest.raises(HTTPError) as err:
        parse(b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: abc\r\n\r\n")
    assert err.value.status == 400


def test_content_length_too_large_is_413():
    with pytest.raises(HTTPError) as err:
        parse(b"POST / HTTP/1.1\r\nHost: x\r\n"
              b"Content-Length: 99999999999\r\n\r\n")
    assert err.value.status == 413


def test_body_shorter_than_content_length_rejected():
    with pytest.raises(HTTPError) as err:
        parse(b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\nxy")
    assert err.value.status == 400


@pytest.mark.parametrize("line", [
    b"GET / HTTP/1.1 EXTRA",        # too many parts
    b"GET /",                       # too few parts
    b"GET",                         # only method
    b"GET  /  HTTP/1.1",            # empty parts
    b"",                            # empty request line
])
def test_malformed_request_lines(line):
    with pytest.raises(HTTPError) as err:
        parse(line + b"\r\nHost: x\r\n\r\n")
    assert err.value.status == 400


def test_missing_host_header_rejected():
    with pytest.raises(HTTPError) as err:
        parse(b"GET / HTTP/1.1\r\nAccept: */*\r\n\r\n")
    assert err.value.status == 400
    assert "Host" in err.value.message


def test_host_not_required_for_http_1_0():
    req = parse(b"GET / HTTP/1.0\r\n\r\n")
    assert req.version == "HTTP/1.0"
    assert req.keep_alive is False


@pytest.mark.parametrize("version", [b"HTTP/2.0", b"HTTP/1.2", b"HTTP/9.9",
                                     b"HTP/1.1", b"http/1.1"])
def test_bad_http_version(version):
    with pytest.raises(HTTPError) as err:
        parse(b"GET / " + version + b"\r\nHost: x\r\n\r\n")
    assert err.value.status == 400


@pytest.mark.parametrize("method", [b"GE T", b"G\x01ET", b"GET/", b"\xff"])
def test_invalid_method_characters(method):
    with pytest.raises(HTTPError) as err:
        parse(method + b" / HTTP/1.1\r\nHost: x\r\n\r\n")
    assert err.value.status == 400


def test_malformed_header_line_rejected():
    with pytest.raises(HTTPError) as err:
        parse(b"GET / HTTP/1.1\r\nHost: x\r\nBadHeaderNoColon\r\n\r\n")
    assert err.value.status == 400


def test_header_with_space_before_colon_rejected():
    with pytest.raises(HTTPError) as err:
        parse(b"GET / HTTP/1.1\r\nHost: x\r\nBad : v\r\n\r\n")
    assert err.value.status == 400


def test_oversized_head_rejected():
    big = b"X-Pad: " + b"A" * (MAX_HEAD_BYTES + 100) + b"\r\n"
    with pytest.raises(HTTPError) as err:
        parse(b"GET / HTTP/1.1\r\nHost: x\r\n" + big + b"\r\n")
    assert err.value.status == 400


def test_oversized_single_line_rejected():
    line = b"GET /" + b"a" * (MAX_HEAD_BYTES + 10) + b" HTTP/1.1\r\n"
    with pytest.raises(HTTPError) as err:
        parse(line + b"Host: x\r\n\r\n")
    assert err.value.status == 400


def test_transfer_encoding_rejected():
    with pytest.raises(HTTPError) as err:
        parse(b"POST / HTTP/1.1\r\nHost: x\r\n"
              b"Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n")
    assert err.value.status == 400


def test_nul_byte_in_path_rejected():
    with pytest.raises(HTTPError) as err:
        parse(b"GET /%00 HTTP/1.1\r\nHost: x\r\n\r\n")
    assert err.value.status == 400


def test_absolute_form_target():
    req = parse(b"GET http://gw.local/api/status?x=1 HTTP/1.1\r\n"
                b"Host: gw.local\r\n\r\n")
    assert req.path == "/api/status"
    assert req.query == {"x": ["1"]}


def test_clean_eof_returns_none():
    assert read_request(io.BytesIO(b"")) is None


def test_form_parsing():
    req = parse(b"POST / HTTP/1.1\r\nHost: x\r\n"
                b"Content-Type: application/x-www-form-urlencoded\r\n"
                b"Content-Length: 27\r\n\r\na=1&a=2&b=hello+world&c=%21")
    form = req.form()
    assert form["a"] == ["1", "2"]
    assert form["b"] == ["hello world"]
    assert form["c"] == ["!"]


def test_json_parsing_and_error():
    req = parse(b"POST / HTTP/1.1\r\nHost: x\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: 11\r\n\r\n{\"key\": 42}")
    assert req.json() == {"key": 42}

    bad = parse(b"POST / HTTP/1.1\r\nHost: x\r\n"
                b"Content-Length: 5\r\n\r\n{oops")
    with pytest.raises(HTTPError) as err:
        bad.json()
    assert err.value.status == 400


def test_keep_alive_semantics():
    req11 = parse(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
    assert req11.keep_alive is True
    req_close = parse(b"GET / HTTP/1.1\r\nHost: x\r\n"
                      b"Connection: close\r\n\r\n")
    assert req_close.keep_alive is False
    req10 = parse(b"GET / HTTP/1.0\r\n\r\n")
    assert req10.keep_alive is False
    req10_ka = parse(b"GET / HTTP/1.0\r\nConnection: keep-alive\r\n\r\n")
    assert req10_ka.keep_alive is True


def test_serialize_response_headers():
    raw = serialize_response(200, [("Content-Type", "text/plain")],
                             "hello", keep_alive=True)
    head, body = raw.split(b"\r\n\r\n", 1)
    assert head.startswith(b"HTTP/1.1 200 OK")
    assert b"Content-Type: text/plain" in head
    assert b"Content-Length: 5" in head
    assert b"Connection: keep-alive" in head
    assert b"Server: gwadmin/" in head
    assert b"Date: " in head
    assert body == b"hello"


def test_serialize_head_only():
    raw = serialize_response(200, [], "hello", head_only=True)
    assert raw.endswith(b"\r\n\r\n")
    assert b"Content-Length: 5" in raw
    assert b"hello" not in raw.split(b"\r\n\r\n", 1)[-1]


def test_serialize_body_types():
    for body in (None, b"", "", bytearray(b"ab")):
        raw = serialize_response(204, [], body)
        assert raw.startswith(b"HTTP/1.1 204")
    with pytest.raises(TypeError):
        serialize_response(200, [], object())


def test_headers_container():
    h = Headers([("A-One", "1"), ("a-one", "2")])
    assert h.get("A-ONE") == "1, 2"
    assert "a-one" in h
    h.set("A-One", "9")
    assert h.get("a-one") == "9"
    assert len(h) == 1
