import socket
import struct

import pytest

from minidns import protocol as P


def _network_available():
    """探测当前环境能否 bind socket（有些沙箱会禁掉）。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        s.close()
        return True
    except OSError:
        return False


NETWORK_AVAILABLE = _network_available()
requires_network = pytest.mark.skipif(
    not NETWORK_AVAILABLE, reason="当前环境禁止 socket 网络操作，跳过网络集成测试")


def udp_exchange(payload, port, host="127.0.0.1", timeout=3.0):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(payload, (host, port))
        data, _ = sock.recvfrom(65535)
        return data
    finally:
        sock.close()


def udp_sendonly(payload, port, host="127.0.0.1"):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(payload, (host, port))
    finally:
        sock.close()


def tcp_exchange(payload, port, host="127.0.0.1", timeout=3.0):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.sendall(len(payload).to_bytes(2, "big") + payload)
        header = _recv_exactly(sock, 2)
        (length,) = struct.unpack("!H", header)
        return _recv_exactly(sock, length)
    finally:
        sock.close()


def _recv_exactly(sock, n):
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise OSError("connection closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def make_query(name, qtype=P.TYPE_A, qid=1, rd=1):
    msg = P.Message()
    msg.id = qid
    msg.rd = rd
    msg.questions.append(P.Question(name, qtype, P.CLASS_IN))
    return msg
