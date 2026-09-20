"""真实 socket 集成测试：起 UDP+TCP 服务，手工发包验证。

在禁止网络操作的沙箱环境里整模块跳过。
"""

import struct
import threading

import pytest

from minidns import protocol as P
from minidns.server import DNSServer, QueryHandler
from minidns.zone import load_zone_dir

from conftest import (make_query, requires_network, tcp_exchange,
                      udp_exchange, udp_sendonly)

pytestmark = requires_network

ZONE_TEXT = """\
$ORIGIN example.com.
$TTL 300
@       IN  NS  ns1
ns1     IN  A   10.0.0.1
www     IN  A   192.168.1.10
www     IN  A   192.168.1.11
www     IN  A   192.168.1.12
web     IN  CNAME www
broken  IN  CNAME nowhere.else.org.
"""

BIG_ZONE = "$ORIGIN huge.test.\n$TTL 60\n" + "".join(
    'big IN TXT "chunk-%02d-%s"\n' % (i, "x" * 100) for i in range(30))


@pytest.fixture()
def server(tmp_path):
    (tmp_path / "example.com.zone").write_text(ZONE_TEXT)
    (tmp_path / "huge.test.zone").write_text(BIG_ZONE)
    zones = load_zone_dir(str(tmp_path))
    srv = DNSServer(QueryHandler(zones=zones), host="127.0.0.1", port=0)
    srv.start()
    yield srv
    srv.shutdown()


def udp_query(name, qtype, port, qid=1):
    return P.Message.decode(
        udp_exchange(make_query(name, qtype, qid=qid).encode(), port))


def test_udp_authoritative(server):
    resp = udp_query("www.example.com", P.TYPE_A, server.port)
    assert resp.rcode == P.RCODE_NOERROR
    assert len(resp.answers) == 3


def test_udp_nxdomain(server):
    assert udp_query("nosuch.example.com", P.TYPE_A,
                     server.port).rcode == P.RCODE_NXDOMAIN


def test_udp_cname_chain(server):
    resp = udp_query("web.example.com", P.TYPE_A, server.port)
    types = [rr.rtype for rr in resp.answers]
    assert P.TYPE_CNAME in types and types.count(P.TYPE_A) == 3


def test_udp_round_robin(server):
    firsts = [udp_query("www.example.com", P.TYPE_A,
                        server.port).answers[0].rdata.address
              for _ in range(3)]
    assert firsts == ["192.168.1.10", "192.168.1.11", "192.168.1.12"]


def test_malformed_truncated_formerr(server):
    resp = P.Message.decode(udp_exchange(b"\x12\x34\x01\x00\x00", server.port))
    assert resp.id == 0x1234
    assert resp.rcode == P.RCODE_FORMERR


def test_malformed_qdcount_lies_formerr(server):
    raw = bytearray(make_query("www.example.com", P.TYPE_A).encode())
    raw[4:6] = struct.pack("!H", 5)
    resp = P.Message.decode(udp_exchange(bytes(raw), server.port))
    assert resp.rcode == P.RCODE_FORMERR


def test_garbage_packets_server_survives(server):
    udp_sendonly(b"\x00", server.port)                    # 太短：丢弃
    udp_sendonly(b"\xff" * 100, server.port)              # 纯垃圾
    udp_sendonly(b"\x00" * 12 + b"\xc0\x0c", server.port)  # 指针环
    resp = udp_query("ns1.example.com", P.TYPE_A, server.port)
    assert resp.rcode == P.RCODE_NOERROR


def test_concurrent_udp_queries(server):
    errors = []

    def worker(n):
        try:
            for i in range(20):
                qid = n * 1000 + i
                resp = udp_query("www.example.com", P.TYPE_A,
                                 server.port, qid=qid)
                assert resp.id == qid
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors


def test_tcp_query(server):
    resp = P.Message.decode(
        tcp_exchange(make_query("www.example.com", P.TYPE_A).encode(),
                     server.port))
    assert resp.rcode == P.RCODE_NOERROR
    assert len(resp.answers) == 3


def test_udp_big_response_tc_bit(server):
    resp = P.Message.decode(
        udp_exchange(make_query("big.huge.test", P.TYPE_TXT).encode(),
                     server.port))
    assert resp.tc == 1
    assert resp.answers == []


def test_tcp_big_response_full(server):
    raw = tcp_exchange(make_query("big.huge.test", P.TYPE_TXT).encode(),
                       server.port)
    resp = P.Message.decode(raw)
    assert resp.tc == 0
    assert len(resp.answers) == 30
    assert len(raw) > 512


def test_cli_query_against_server(server, capsys):
    from minidns.cli import main
    rc = main(["query", "--server", "127.0.0.1:%d" % server.port,
               "www.example.com", "A"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "status: NOERROR" in out
    assert "192.168.1.1" in out
