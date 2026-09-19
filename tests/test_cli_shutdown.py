import signal
import socket
import subprocess
import sys
from pathlib import Path


def test_cli_starts_serves_and_shuts_on_sigint(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "index.html").write_text("cli index", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "miniweb",
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--root",
            str(root),
            "--workers",
            "2",
        ],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    port = None
    try:
        first_line = proc.stdout.readline()
        assert "miniweb listening" in first_line
        port = int(first_line.rsplit(":", 1)[1].strip())

        with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
            sock.sendall(b"GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
        assert b"200 OK" in data
        assert b"cli index" in data

        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=5)
        assert proc.returncode == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)
        if proc.returncode not in (None, 0):
            stderr = proc.stderr.read() if proc.stderr else ""
            raise AssertionError(f"CLI failed with {proc.returncode}:\n{stderr}")
