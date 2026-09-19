import json
import socket

from helpers import http_request, parse_response, raw_request


def test_form_urlencoded_decodes_spaces_percent_and_repeats(port):
    payload = (
        b"POST /form HTTP/1.1\r\n"
        b"Host: localhost\r\n"
        b"Content-Type: application/x-www-form-urlencoded\r\n"
        b"Content-Length: 36\r\n\r\n"
        b"name=Jane+Doe&city=S%26F&tag=a&tag=b"
    )
    status, headers, body, *_ = parse_response(raw_request(port, payload))
    assert status == 200
    data = json.loads(body)
    assert data["name"] == "Jane Doe"
    assert data["city"] == "S&F"
    assert data["tag"] == ["a", "b"]


def test_blank_form_values_are_preserved(port):
    status, headers, body, *_ = http_request(
        port,
        "POST",
        "/form",
        b"empty=&x=%20",
        {"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert status == 200
    assert json.loads(body) == {"empty": "", "x": " "}


def test_json_body_accepted(port):
    raw = json.dumps({"hello": "world", "n": [1, 2]}).encode()
    status, headers, body, *_ = http_request(
        port, "POST", "/json", raw, {"Content-Type": "application/json"}
    )
    assert status == 200
    assert headers["content-type"] == "application/json"
    assert json.loads(body) == {"hello": "world", "n": [1, 2]}


def test_invalid_json_returns_400(port):
    status, headers, body, *_ = http_request(
        port, "POST", "/json", b"{not json", {"Content-Type": "application/json"}
    )
    assert status == 400
    assert b"400 Bad Request" in body


def test_json_wrong_content_type_returns_400(port):
    status, headers, body, *_ = http_request(
        port, "POST", "/json", b"{}", {"Content-Type": "text/plain"}
    )
    assert status == 400


def test_exact_content_length_with_pipelined_second_request(port):
    # First body is exactly four bytes; later bytes belong to next request.
    first = (
        b"POST /form HTTP/1.1\r\nHost: x\r\n"
        b"Content-Type: application/x-www-form-urlencoded\r\n"
        b"Content-Length: 4\r\nConnection: keep-alive\r\n\r\na=12"
    )
    second = b"GET /hello HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"

    with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
        sock.sendall(first + second)
        data = b""
        while data.count(b"HTTP/1.1") < 2:
            chunk = sock.recv(8192)
            if not chunk:
                break
            data += chunk
    assert b"200 OK" in data
    assert data.count(b"200 OK") >= 2


def test_expect_100_continue(port):
    request = (
        b"POST /form HTTP/1.1\r\nHost: x\r\n"
        b"Content-Type: application/x-www-form-urlencoded\r\n"
        b"Content-Length: 7\r\nExpect: 100-continue\r\n\r\n"
        b"name=ok"
    )
    with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
        sock.sendall(request)
        data = b""
        while b"200 OK" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    assert b"HTTP/1.1 100 Continue" in data
    assert b"200 OK" in data


def test_three_repeated_form_keys_become_list(port):
    raw_body = b"a=1&a=2&a=3"
    status, headers, body, *_ = http_request(
        port,
        "POST",
        "/form",
        raw_body,
        {"Content-Type": "application/x-www-form-urlencoded",
         "Content-Length": str(len(raw_body))},
    )
    assert status == 200
    assert json.loads(body)["a"] == ["1", "2", "3"]
