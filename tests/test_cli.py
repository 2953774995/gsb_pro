"""CLI argument parsing and end-to-end subprocess launch (where permitted)."""

import socket
import subprocess
import sys
import time

import pytest

from miniweb.cli import build_parser


def test_arg_defaults():
    args = build_parser().parse_args([])
    assert args.host == "127.0.0.1"
    assert args.port == 8000
    assert args.workers == 10
    assert args.timeout == 30.0
    assert args.root == ""


def test_arg_parsing():
    args = build_parser().parse_args(
        ["--host", "0.0.0.0", "--port", "9000", "--root", "/tmp/www",
         "--workers", "4", "--timeout", "12"]
    )
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.workers == 4
    assert args.timeout == 12.0
    assert args.root == "/tmp/www"


def _port_free():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
    except OSError:
        return None
    finally:
        probe.close()


def test_cli_subprocess_static_and_routes():
    import os

    port = _port_free()
    if port is None:
        pytest.skip("environment forbids TCP socket binding")
    static_root = os.path.join(os.path.dirname(__file__), "static")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "miniweb",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--root",
            static_root,
            "--workers",
            "4",
        ],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.time() + 10
        ready = False
        while time.time() < deadline:
            conn = socket.create_connection(("127.0.0.1", port), timeout=1)
            conn.sendall(b"GET /hello HTTP/1.1\r\nHost: x\r\n\r\n")
            data = conn.recv(4096)
            conn.close()
            if b"200 OK" in data:
                ready = True
                break
            time.sleep(0.2)
        assert ready

        def request(raw):
            conn = socket.create_connection(("127.0.0.1", port), timeout=2)
            conn.sendall(raw)
            chunks = []
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            conn.close()
            return b"".join(chunks)

        index = request(
            b"GET /index.html HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"
        )
        assert b"200 OK" in index and b"Hello from miniweb" in index

        form = request(
            b"POST /echo HTTP/1.1\r\nHost: x\r\nConnection: close\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n"
            b"Content-Length: 8\r\n\r\nname=alice"
        )
        assert b"200 OK" in form and b'"name": "alice"' in form

        missing = request(
            b"GET /nope HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"
        )
        assert b"404" in missing

        method = request(
            b"DELETE /hello HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"
        )
        assert b"405" in method and b"Allow:" in method

        # SIGINT must produce a clean exit.
        proc.send_signal(__import__("signal").SIGINT)
        proc.wait(timeout=10)
        output = proc.stdout.read()
        assert proc.returncode == 0
        assert "shutting down" in output
        assert "GET /hello 200" in output  # access log line
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
