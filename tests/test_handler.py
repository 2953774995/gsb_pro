"""查询处理核心（QueryHandler）测试：不依赖 socket，直接喂报文字节。

权威应答 / CNAME 链 / 轮询 / 畸形报文 / UDP 截断逻辑 / 并发。
"""

import struct
import threading

import pytest

from minidns import protocol as P
from minidns.server import QueryHandler
from minidns.zone import ZoneParser

from conftest import make_query

ZONE_TEXT = """\
$ORIGIN example.com.
$TTL 300
@       IN  NS  ns1
ns1     IN  A   10.0.0.1
www     IN  A   192.168.1.10
www     IN  A   192.168.1.11
www     IN  A   192.168.1.12
web     IN  CNAME www
chain   IN  CNAME web
broken  IN  CNAME nowhere.else.org.
mail    IN  MX 10 mail.example.com.
big     IN  TXT "chunk-00-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
"""

BIG_ZONE = "$ORIGIN huge.test.\n$TTL 60\n" + "".join(
    'big IN TXT "chunk-%02d-%s"\n' % (i, "x" * 100) for i in range(30))


@pytest.fixture()
def handler():
    zone = ZoneParser(filename="test.zone").parse_text(ZONE_TEXT)
    return QueryHandler(zones=[zone])


@pytest.fixture()
def big_handler():
    zone = ZoneParser(filename="big.zone").parse_text(BIG_ZONE)
    return QueryHandler(zones=[zone])


def ask(handler, name, qtype=P.TYPE_A, qid=1, via_tcp=False):
    raw = handler.process(make_query(name, qtype, qid=qid).encode(),
                          ("127.0.0.1", 53535), via_tcp=via_tcp)
    return P.Message.decode(raw)


# ---------------------------------------------------------------- 权威应答

def test_authoritative_a(handler):
    resp = ask(handler, "www.example.com")
    assert resp.rcode == P.RCODE_NOERROR and resp.aa == 1
    assert {rr.rdata.address for rr in resp.answers} == {
        "192.168.1.10", "192.168.1.11", "192.168.1.12"}


def test_case_insensitive(handler):
    resp = ask(handler, "WWW.Example.COM")
    assert resp.rcode == P.RCODE_NOERROR
    assert len(resp.answers) == 3


def test_nxdomain(handler):
    resp = ask(handler, "nosuch.example.com")
    assert resp.rcode == P.RCODE_NXDOMAIN


def test_nodata(handler):
    resp = ask(handler, "ns1.example.com", P.TYPE_AAAA)
    assert resp.rcode == P.RCODE_NOERROR
    assert resp.answers == []


def test_unsupported_type(handler):
    assert ask(handler, "www.example.com", 65).rcode == P.RCODE_NOERROR
    assert ask(handler, "nosuch.example.com", 65).rcode == P.RCODE_NXDOMAIN


def test_round_robin(handler):
    firsts = [ask(handler, "www.example.com").answers[0].rdata.address
              for _ in range(4)]
    assert firsts == ["192.168.1.10", "192.168.1.11",
                      "192.168.1.12", "192.168.1.10"]


def test_cname_chain(handler):
    resp = ask(handler, "chain.example.com")
    assert resp.rcode == P.RCODE_NOERROR
    types = [rr.rtype for rr in resp.answers]
    assert types.count(P.TYPE_CNAME) == 2
    assert types.count(P.TYPE_A) == 3
    assert resp.answers[0].rdata.name == "web.example.com"


def test_cname_broken_chain(handler):
    resp = ask(handler, "broken.example.com")
    assert resp.rcode == P.RCODE_NXDOMAIN
    assert any(rr.rtype == P.TYPE_CNAME for rr in resp.answers)


def test_out_of_zone_refused_without_upstream(handler):
    assert ask(handler, "other.org").rcode == P.RCODE_REFUSED


def test_mx_query(handler):
    resp = ask(handler, "mail.example.com", P.TYPE_MX)
    assert resp.answers[0].rdata.preference == 10
    assert resp.answers[0].rdata.exchange == "mail.example.com"


# ---------------------------------------------------------------- 畸形报文

def test_truncated_packet_formerr(handler):
    raw = handler.process(b"\x12\x34\x01\x00\x00",
                          ("127.0.0.1", 1), via_tcp=False)
    resp = P.Message.decode(raw)
    assert resp.id == 0x1234
    assert resp.rcode == P.RCODE_FORMERR


def test_qdcount_lies_formerr(handler):
    raw = bytearray(make_query("www.example.com", P.TYPE_A).encode())
    raw[4:6] = struct.pack("!H", 5)
    resp = P.Message.decode(
        handler.process(bytes(raw), ("127.0.0.1", 1), via_tcp=False))
    assert resp.rcode == P.RCODE_FORMERR


def test_tiny_packet_dropped(handler):
    assert handler.process(b"\x00", ("127.0.0.1", 1), via_tcp=False) is None


def test_pointer_loop_packet_formerr(handler):
    # 合法头部 + QDCOUNT=1，问题名字是自指压缩指针
    raw = b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00" + \
        b"\xc0\x0c" + b"\x00\x01\x00\x01"
    resp = P.Message.decode(
        handler.process(raw, ("127.0.0.1", 1), via_tcp=False))
    assert resp.rcode == P.RCODE_FORMERR


def test_response_packet_dropped(handler):
    # QR=1 的报文不是查询，直接丢弃
    msg = make_query("www.example.com", P.TYPE_A)
    msg.qr = 1
    assert handler.process(msg.encode(), ("127.0.0.1", 1), via_tcp=False) is None


def test_nonzero_opcode_notimp(handler):
    msg = make_query("www.example.com", P.TYPE_A)
    msg.opcode = 2
    resp = P.Message.decode(
        handler.process(msg.encode(), ("127.0.0.1", 1), via_tcp=False))
    assert resp.rcode == P.RCODE_NOTIMP


def test_empty_question_formerr(handler):
    msg = P.Message()
    msg.id = 7
    resp = P.Message.decode(
        handler.process(msg.encode(), ("127.0.0.1", 1), via_tcp=False))
    assert resp.rcode == P.RCODE_FORMERR


# ---------------------------------------------------------------- 截断

def test_udp_over_512_truncated(big_handler):
    resp = ask(big_handler, "big.huge.test", P.TYPE_TXT, via_tcp=False)
    assert resp.tc == 1
    assert resp.answers == []


def test_tcp_over_512_full(big_handler):
    resp = ask(big_handler, "big.huge.test", P.TYPE_TXT, via_tcp=True)
    assert resp.tc == 0
    assert len(resp.answers) == 30
    assert len(resp.encode()) > 512


# ---------------------------------------------------------------- 并发

def test_concurrent_process_no_mixup(handler):
    errors = []

    def worker(n):
        try:
            for i in range(50):
                name = ["www.example.com", "ns1.example.com",
                        "nosuch.example.com"][i % 3]
                resp = ask(handler, name, qid=n * 1000 + i)
                assert resp.id == n * 1000 + i
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors
