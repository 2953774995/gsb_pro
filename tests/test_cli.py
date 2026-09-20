import io
import socket

from minibroker.broker import Broker
from minibroker.persistence import AppendOnlyLog
from minibroker.server import BrokerServer, Connection
from minibroker.cli import run_cli


def test_cli_help_ping_and_quit(monkeypatch):
    broker = Broker(AppendOnlyLog.null(), retention=10)
    server = BrokerServer(broker=broker)
    connections = []

    def fake_create_connection(_address, timeout=None, *_args, **_kwargs):
        client_sock, server_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        client_sock.settimeout(timeout)
        conn = Connection(server_sock, ("socketpair", 0), broker, server)
        server._connections.append(conn)
        connections.append(conn)
        conn.start()
        return client_sock

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    monkeypatch.setattr("sys.stdin", io.StringIO("help\nping\nquit\n"))
    stdout = io.StringIO()
    monkeypatch.setattr("sys.stdout", stdout)

    code = run_cli(["--host", "127.0.0.1", "--port", "7379"])
    assert code == 0
    output = stdout.getvalue()
    assert "commands:" in output
    assert "PONG" in output

    for conn in connections:
        conn.close()
    broker.close()
