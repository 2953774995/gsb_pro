import json
import socket


def send_raw(server, payload, read_bytes=4096):
    sock = server.connect()
    sock.sendall(payload)
    data = sock.recv(read_bytes)
    sock.close()
    return data


def parse_headers(raw):
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    status = int(lines[0].split()[1])
    headers = {}
    for line in lines[1:]:
        key, _, value = line.partition(b":")
        headers[key.decode().lower()] = value.strip().decode()
    return status, headers, body


def test_server_rejects_malformed_requests(server_factory):
    server = server_factory()
    for payload in [
        b"GARBAGE\r\n\r\n",
        b"GET / HTTP/1.1\r\n\r\n",
        b"GET / HTTP/2.0\r\nHost: x\r\n\r\n",
        b"GET / HTTP/1.1\r\nHost: x\r\nBadHeader\r\n\r\n",
        b"GET / HTTP/1.1\r\nHost: x\r\nX-Bad: bad\x00value\r\n\r\n",
    ]:
        status, headers, body = parse_headers(send_raw(server, payload))
        assert status == 400
        assert b"400 Bad Request" in body


def test_status_and_config_business_chain(server_factory, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    server = server_factory(root=root, config_path=tmp_path / "config.json")

    status, headers, body = parse_headers(
        send_raw(
            server,
            b"GET /api/status HTTP/1.1\r\nHost: gw\r\nConnection: close\r\n\r\n",
        )
    )
    assert status == 200
    assert headers["content-type"].startswith("application/json")
    payload = json.loads(body)
    assert payload["version"]
    assert payload["worker_threads"] == 8
    assert payload["requests_handled"] == 1

    form = b"sample_interval=2500&alarm_threshold=91.5"
    status, _, body = parse_headers(
        send_raw(
            server,
            (
                b"POST /api/config HTTP/1.1\r\nHost: gw\r\n"
                b"Content-Type: application/x-www-form-urlencoded\r\n"
                + f"Content-Length: {len(form)}\r\nConnection: close\r\n\r\n".encode()
                + form
            ),
        )
    )
    assert status == 200
    saved = json.loads(body)
    assert saved["sample_interval"] == 2500
    assert saved["alarm_threshold"] == 91.5
    assert json.loads((tmp_path / "config.json").read_text())["sample_interval"] == 2500

    status, _, body = parse_headers(
        send_raw(server, b"GET /api/config HTTP/1.1\r\nHost: gw\r\nConnection: close\r\n\r\n")
    )
    assert status == 200
    assert json.loads(body)["sample_interval"] == 2500


def test_config_form_decoding_json_and_validation(server_factory, tmp_path):
    server = server_factory(root=tmp_path / "root", config_path=tmp_path / "c.json")
    body = b'{"sample_interval": 10, "alarm_threshold": 50}'
    raw = send_raw(
        server,
        (
            b"POST /api/config HTTP/1.1\r\nHost: gw\r\nContent-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        ),
    )
    status, _, response_body = parse_headers(raw)
    assert status == 400
    assert b"sample_interval" in response_body

    body = b"{not-json"
    raw = send_raw(
        server,
        (
            b"POST /api/config HTTP/1.1\r\nHost: gw\r\nContent-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        ),
    )
    assert parse_headers(raw)[0] == 400

    body = b"sample_interval=1500&sample_interval=2000"
    raw = send_raw(
        server,
        (
            b"POST /api/config HTTP/1.1\r\nHost: gw\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n"
            + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        ),
    )
    assert parse_headers(raw)[0] == 400


def test_404_405_and_error_pages_on_real_server(server_factory, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    server = server_factory(root=root)
    status, _, body = parse_headers(
        send_raw(server, b"GET /missing HTTP/1.1\r\nHost: gw\r\nConnection: close\r\n\r\n")
    )
    assert status == 404 and b"404 Not Found" in body

    status, headers, body = parse_headers(
        send_raw(server, b"DELETE /api/status HTTP/1.1\r\nHost: gw\r\nConnection: close\r\n\r\n")
    )
    assert status == 405
    assert "GET" in headers["allow"]
    assert b"405" in body


def test_handler_exception_becomes_500_without_stack(server_factory, tmp_path):
    app_root = tmp_path / "root"
    app_root.mkdir()
    from gwadmin.app import Application

    app = Application(root=str(app_root), config_path=str(tmp_path / "c.json"))
    app.router.get("/boom", lambda request: (_ for _ in ()).throw(RuntimeError("secret traceback")))
    server = server_factory(app=app)
    status, _, body = parse_headers(
        send_raw(server, b"GET /boom HTTP/1.1\r\nHost: gw\r\nConnection: close\r\n\r\n")
    )
    assert status == 500
    assert b"secret traceback" not in body
    assert b"500 Internal Server Error" in body


def test_413_large_body_and_400_truncated_body(server_factory, tmp_path):
    server = server_factory(root=tmp_path / "root", config_path=tmp_path / "c.json", body_limit=8)
    body = b"x" * 20
    status, _, response_body = parse_headers(
        send_raw(
            server,
            b"POST /api/config HTTP/1.1\r\nHost: gw\r\nContent-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body,
        )
    )
    assert status == 413
    assert b"413 Payload Too Large" in response_body

    sock = server.connect()
    sock.sendall(
        b"POST /api/config HTTP/1.1\r\nHost: gw\r\nContent-Length: 5\r\n"
        b"Connection: close\r\n\r\nabc"
    )
    sock.shutdown(socket.SHUT_WR)
    status, _, _ = parse_headers(sock.recv(4096))
    sock.close()
    assert status == 400
