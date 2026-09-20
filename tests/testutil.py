import socket

from linebus.client import LinebusClient
from linebus.server import LinebusServer


def attach_pair(server, *, timeout=None):
    """Return an SDK client connected to an unbound server via socketpair."""
    server_sock, client_sock = socket.socketpair()
    server._spawn_connection(server_sock, ("socketpair", server._next_connection_id))
    client = LinebusClient("127.0.0.1", 0, timeout=timeout)
    client.attach_socket(client_sock)
    return client
