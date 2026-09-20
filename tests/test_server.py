"""服务器集成测试：真实 UDP/TCP 起服务（临时端口）、并发、畸形报文、大响应。

沙箱环境禁止 bind() 时，真实 socket 的用例自动 skip；
报文级处理逻辑（handle_query）的用例不依赖网络，始终运行。
"""

import socket
import struct
import threading

import pytest

from minidns.protocol import (CLASS_IN, TYPE_A, TYPE_TXT, Header, Message,
                              Question, RCODE_FORMERR, RCODE_NOERROR,
                              RCODE_NOTIMP, RCODE_NXDOMAIN, Record)
from minidns.server import DNSServer, truncate_message
from minidns.zone import Zone, ZoneStore, parse_zone

ZONE_TEXT = """
$ORIGIN example.com.
$TTL 300
@       IN  A   10.0.0.1
        IN  A   10.0.0.2
www     IN  A   10.0.0.10
web     IN  CNAME   www
lost    IN  CNAME   nowhere
txt     IN  TXT "hello"
"""


def make_store(text=ZONE_TEXT):
    origin, records = parse_zone(text)
    zone = Zone(origin)
    for r in records:
        zone.add(r)
    store = ZoneStore()
    store.add_zone(zone)
    return store


def make_server(text=ZONE_TEXT):
    return DNSServer(zone_store=make_store(text), host='127.0.0.1', port=0)


def raw_query(name, qtype=TYPE_A, qid=0x42, opcode=0, qdcount=1):
    msg = Message(Header(id=qid, rd=1, opcode=opcode))
    msg.questions.append(Question(name, qtype))
    data = msg.to_bytes()
    if qdcount != 1:
        data = data[:4] + struct.pack('!H', qdcount) + data[6:]
    return data


# ---------------------------------------------------------------------------
# 报文级处理（不需要 socket）
# ---------------------------------------------------------------------------

def test_authoritative_answer():
    server = make_server()
    resp = Message.parse(server.handle_query(raw_query('www.example.com')))
    assert resp.header.qr == 1 and resp.header.aa == 1
    assert resp.header.rcode == RCODE_NOERROR
    assert resp.answers[0].rdata == '10.0.0.10'


def test_round_robin_over_server():
    server = make_server()
    firsts = []
    for _ in range(4):
        resp = Message.parse(server.handle_query(raw_query('example.com')))
        firsts.append(resp.answers[0].rdata)
    assert firsts[0] != firsts[1]
    assert firsts[0] == firsts[2]
    assert set(firsts) == {'10.0.0.1', '10.0.0.2'}


def test_cname_chain_over_server():
    server = make_server()
    resp = Message.parse(server.handle_query(raw_query('web.example.com')))
    assert resp.header.rcode == RCODE_NOERROR
    assert resp.answers[0].type == 5  # CNAME
    assert resp.answers[0].rdata == 'www.example.com.'
    assert resp.answers[1].rdata == '10.0.0.10'


def test_broken_cname_nxdomain():
    server = make_server()
    resp = Message.parse(server.handle_query(raw_query('lost.example.com')))
    assert resp.header.rcode == RCODE_NXDOMAIN


def test_unsupported_type_does_not_crash():
    server = make_server()
    resp = Message.parse(server.handle_query(raw_query('www.example.com', 65)))
    # TYPE65 不在区域内 -> NODATA（NOERROR 空应答），进程不崩
    assert resp.header.rcode == RCODE_NOERROR
    assert resp.answers == []


def test_unknown_name_nxdomain():
    server = make_server()
    resp = Message.parse(server.handle_query(raw_query('nope.example.com')))
    assert resp.header.rcode == RCODE_NXDOMAIN


def test_malformed_truncated_dropped():
    server = make_server()
    assert server.handle_query(b'\x00\x01\x02', 'test') is None  # 不足 12 字节


def test_malformed_qdcount_lies_formerr():
    server = make_server()
    resp = Message.parse(server.handle_query(raw_query('www.example.com',
                                                       qdcount=5)))
    assert resp.header.rcode == RCODE_FORMERR
    assert resp.header.id == 0x42  # 尽量回显原 ID


def test_malformed_garbage_formerr_or_drop():
    server = make_server()
    garbage = bytes(range(256)) * 3  # 足够长但内容非法
    result = server.handle_query(garbage, 'test')
    if result is not None:
        resp = Message.parse(result)
        assert resp.header.rcode == RCODE_FORMERR


def test_nonzero_opcode_notimp():
    server = make_server()
    resp = Message.parse(server.handle_query(
        raw_query('www.example.com', opcode=2)))  # STATUS
    assert resp.header.rcode == RCODE_NOTIMP


def test_truncate_message_sets_tc_and_clears_answers():
    msg = Message(Header(id=1, qr=1, aa=1))
    msg.questions.append(Question('big.example.com', TYPE_TXT))
    msg.answers = [Record('big.example.com', TYPE_TXT, CLASS_IN, 300,
                          ['x' * 100]) for _ in range(10)]
    data = msg.to_bytes()
    assert len(data) > 512
    truncated = Message.parse(truncate_message(data))
    assert truncated.header.tc == 1
    assert truncated.answers == []
    assert len(truncated.to_bytes()) <= 512


def test_concurrent_handle_query_no_crosstalk():
    server = make_server()
    results = {}
    errors = []

    def worker(i):
        try:
            name = 'www.example.com' if i % 2 == 0 else 'web.example.com'
            resp = Message.parse(server.handle_query(
                raw_query(name, qid=1000 + i), 'client-%d' % i))
            results[i] = (resp.header.id, name,
                          [r.rdata for r in resp.answers])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(results) == 40
    for i, (qid, name, rdata) in results.items():
        assert qid == 1000 + i  # 每个客户端拿到自己的 ID，不串包
        if i % 2 == 0:
            assert '10.0.0.10' in rdata
        else:
            assert 'www.example.com.' in rdata


# ---------------------------------------------------------------------------
# 真实 socket 集成（沙箱禁网时 skip）
# ---------------------------------------------------------------------------

def _can_bind():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(('127.0.0.1', 0))
        s.close()
        return True
    except OSError:
        return False


needs_network = pytest.mark.skipif(not _can_bind(),
                                   reason='当前环境禁止绑定 socket')


def udp_exchange(port, payload, timeout=5):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(payload, ('127.0.0.1', port))
        return sock.recvfrom(65535)[0]
    finally:
        sock.close()


def tcp_exchange(port, payload, timeout=5):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect(('127.0.0.1', port))
        sock.sendall(struct.pack('!H', len(payload)) + payload)
        hdr = b''
        while len(hdr) < 2:
            hdr += sock.recv(2 - len(hdr))
        (length,) = struct.unpack('!H', hdr)
        data = b''
        while len(data) < length:
            data += sock.recv(length - len(data))
        return data
    finally:
        sock.close()


@pytest.fixture
def running_server():
    server = make_server()
    server.start()
    yield server
    server.stop()


@needs_network
def test_udp_query_real_server(running_server):
    resp = Message.parse(udp_exchange(running_server.port,
                                      raw_query('www.example.com')))
    assert resp.answers[0].rdata == '10.0.0.10'


@needs_network
def test_udp_concurrent_queries_no_crosstalk(running_server):
    results = {}

    def worker(i):
        name = 'www.example.com' if i % 2 == 0 else 'web.example.com'
        resp = Message.parse(udp_exchange(running_server.port,
                                          raw_query(name, qid=2000 + i)))
        results[i] = (resp.header.id, [r.rdata for r in resp.answers])

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 30
    for i, (qid, rdata) in results.items():
        assert qid == 2000 + i


@needs_network
def test_udp_malformed_does_not_kill_server(running_server):
    # 连发畸形报文，服务必须活着且后续正常查询不受影响
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(2)
        sock.sendto(b'\x00' * 3, ('127.0.0.1', running_server.port))  # 丢弃
        sock.sendto(raw_query('www.example.com', qdcount=9),
                    ('127.0.0.1', running_server.port))  # FORMERR
        data, _ = sock.recvfrom(65535)
        assert Message.parse(data).header.rcode == RCODE_FORMERR
        # 服务仍然正常
        resp = Message.parse(udp_exchange(running_server.port,
                                          raw_query('www.example.com')))
        assert resp.answers[0].rdata == '10.0.0.10'
    finally:
        sock.close()


BIG_ZONE = "$ORIGIN big.test.\n$TTL 300\n" + ''.join(
    'r%03d IN A 10.1.%d.%d\n' % (i, i // 256, i % 256) for i in range(80)) + \
    'all IN TXT "' + 'y' * 200 + '"\n' + ''.join(
        'all IN TXT "chunk-%02d-%s"\n' % (i, 'z' * 40) for i in range(20))


@needs_network
def test_udp_truncates_big_response_tcp_gets_all():
    server = make_server(BIG_ZONE)
    server.start()
    try:
        payload = raw_query('all.big.test', TYPE_TXT)
        # UDP：超过 512 字节 -> TC=1 且无 Answer
        udp_resp = Message.parse(udp_exchange(server.port, payload))
        assert udp_resp.header.tc == 1
        assert udp_resp.answers == []
        # TCP：拿到完整应答
        tcp_resp = Message.parse(tcp_exchange(server.port, payload))
        assert tcp_resp.header.tc == 0
        assert len(tcp_resp.answers) == 21
        assert len(tcp_resp.to_bytes()) > 512
    finally:
        server.stop()


@needs_network
def test_tcp_multiple_queries_one_connection(running_server):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(5)
        sock.connect(('127.0.0.1', running_server.port))
        for qid in (1, 2, 3):
            payload = raw_query('www.example.com', qid=qid)
            sock.sendall(struct.pack('!H', len(payload)) + payload)
            hdr = sock.recv(2)
            (length,) = struct.unpack('!H', hdr)
            data = b''
            while len(data) < length:
                data += sock.recv(length - len(data))
            resp = Message.parse(data)
            assert resp.header.id == qid
            assert resp.answers[0].rdata == '10.0.0.10'
    finally:
        sock.close()
