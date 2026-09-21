import socket


def send(server, payload):
    sock = server.connect()
    sock.sendall(payload)
    chunks = []
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
    sock.close()
    raw = b"".join(chunks)
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    status = int(lines[0].split()[1])
    headers = {}
    for line in lines[1:]:
        key, _, value = line.partition(b":")
        headers[key.decode().lower()] = value.strip().decode()
    return status, headers, body


def test_static_mime_default_page_404_and_traversal(server_factory, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "index.html").write_text("<h1>index</h1>", encoding="utf-8")
    (root / "app.js").write_text("console.log('js')", encoding="utf-8")
    sub = root / "sub"
    sub.mkdir()
    (sub / "index.html").write_text("<h1>sub</h1>", encoding="utf-8")
    server = server_factory(root=root)

    status, headers, body = send(
        server, b"GET /app.js HTTP/1.1\r\nHost: gw\r\nConnection: close\r\n\r\n"
    )
    assert status == 200
    assert headers["content-type"] == "application/javascript; charset=utf-8"
    assert b"console.log" in body

    status, _, body = send(server, b"GET / HTTP/1.1\r\nHost: gw\r\nConnection: close\r\n\r\n")
    assert status == 200 and b"<h1>index</h1>" in body

    status, headers, _ = send(
        server, b"GET /sub HTTP/1.1\r\nHost: gw\r\nConnection: close\r\n\r\n"
    )
    assert status == 301 and headers["location"] == "/sub/"


    empty = root / "empty"
    empty.mkdir()
    status, _, _ = send(
        server,
        b"GET /empty/ HTTP/1.1\r\nHost: gw\r\nConnection: close\r\n\r\n",
    )
    assert status == 403

    status, headers, head_body = send(
        server, b"HEAD /app.js HTTP/1.1\r\nHost: gw\r\nConnection: close\r\n\r\n"
    )
    assert status == 200
    assert int(headers["content-length"]) > 0
    assert head_body == b""

    status, post_headers, _ = send(
        server, b"POST /app.js HTTP/1.1\r\nHost: gw\r\nConnection: close\r\n\r\n"
    )
    assert status == 405 and post_headers["allow"] == "GET, HEAD"

    status, _, body = send(
        server, b"GET /no-such-file HTTP/1.1\r\nHost: gw\r\nConnection: close\r\n\r\n"
    )
    assert status == 404 and b"Not Found" in body

    for path in [
        "/../config.json",
        "/%2e%2e/config.json",
        "/sub/../../config.json",
        "/%2e%2e%2fconfig.json",
    ]:
        status, _, body = send(
            server,
            f"GET {path} HTTP/1.1\r\nHost: gw\r\nConnection: close\r\n\r\n".encode(),
        )
        assert status == 404, path
        assert b"sample_interval" not in body
