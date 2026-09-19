"""End-to-end CLI tests (require real loopback TCP)."""

import subprocess
import sys
import time

import pytest

from tests.conftest import TCP_AVAILABLE, requires_tcp

if not TCP_AVAILABLE:
    pytest.skip("CLI tests need TCP", allow_module_level=True)


def _wait_port_free_then_start(aof_path, port):
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "minibroker",
            "--host", "127.0.0.1", "--port", str(port),
            "--aof", aof_path,
        ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.time() + 5
    import socket as socket_mod
    while time.time() < deadline:
        probe = socket_mod.socket()
        probe.settimeout(0.2)
        try:
            probe.connect(("127.0.0.1", port))
            probe.close()
            return proc
        except OSError:
            time.sleep(0.05)
        finally:
            try:
                probe.close()
            except OSError:
                pass
    proc.kill()
    raise AssertionError("broker did not start: %s" % proc.stderr.read())


def test_mb_cli_publish_subscribe(tmp_path):
    import socket
    port = 43123
    aof = str(tmp_path / "cli.aof")
    broker = _wait_port_free_then_start(aof, port)
    repo_root = str(__import__("pathlib").Path(__file__).resolve().parents[1])
    try:
        sub = subprocess.Popen(
            [
                sys.executable, "mb-cli",
                "--host", "127.0.0.1", "--port", str(port),
                "-c", "subscribe demo",
                "-c", "recv 3",
            ],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(0.6)
        pub = subprocess.run(
            [
                sys.executable, "mb-cli",
                "--host", "127.0.0.1", "--port", str(port),
                "-c", "publish demo hello world",
                "-c", "ping",
            ],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        assert pub.returncode == 0, pub.stderr
        assert "published seq=1" in pub.stdout
        assert "PONG" in pub.stdout
        out, err = sub.communicate(timeout=6)
        assert sub.returncode == 0, err
        assert "MSG" in out and "hello world" in out
    finally:
        subprocess.run(
            [
                sys.executable, "mb-cli",
                "--host", "127.0.0.1", "--port", str(port),
                "-c", "shutdown",
            ],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        try:
            broker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            broker.kill()


def test_server_module_restarts_with_aof(tmp_path):
    import socket
    port = 43124
    aof = str(tmp_path / "srv.aof")
    repo_root = str(__import__("pathlib").Path(__file__).resolve().parents[1])
    broker = _wait_port_free_then_start(aof, port)
    try:
        first = subprocess.run(
            [
                sys.executable, "mb-cli",
                "--host", "127.0.0.1", "--port", str(port),
                "-c", "publish keep me",
            ],
            cwd=repo_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=5,
        )
        assert "published seq=1" in first.stdout
    finally:
        subprocess.run(
            [
                sys.executable, "mb-cli",
                "--host", "127.0.0.1", "--port", str(port),
                "-c", "shutdown",
            ],
            cwd=repo_root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5,
        )
        broker.wait(timeout=5)

    broker2 = _wait_port_free_then_start(aof, port)
    try:
        read_back = subprocess.run(
            [
                sys.executable, "mb-cli",
                "--host", "127.0.0.1", "--port", str(port),
                "-c", "subscribe keep",
                "-c", "recv 2",
            ],
            cwd=repo_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=6,
        )
        assert "seq=1" in read_back.stdout and "me" in read_back.stdout
    finally:
        subprocess.run(
            [
                sys.executable, "mb-cli",
                "--host", "127.0.0.1", "--port", str(port),
                "-c", "shutdown",
            ],
            cwd=repo_root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5,
        )
        try:
            broker2.wait(timeout=5)
        except subprocess.TimeoutExpired:
            broker2.kill()
