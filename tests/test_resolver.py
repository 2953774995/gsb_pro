"""递归转发：缓存命中/过期、按类型分 key、singleflight、上游失败 SERVFAIL。

大部分测试用假的 _exchange 注入，不依赖真实网络；
末尾有真实 socket 的上游集成测试（沙箱里自动跳过）。
"""

import threading
import time

import pytest

from minidns import protocol as P
from minidns.cache import DNSCache
from minidns.resolver import UpstreamResolver

from conftest import make_query, requires_network, udp_exchange


def canned_response(query, records, rcode=P.RCODE_NOERROR):
    resp = query.make_response(rcode)
    resp.ra = 1
    resp.answers = records
    return resp


def a_rr(name, addr, ttl=60):
    return P.ResourceRecord(name, P.TYPE_A, P.CLASS_IN, ttl, P.ARecord(addr))


class FakeUpstream:
    """替换 UpstreamResolver._exchange 的假上游。"""

    def __init__(self, records_by_name=None, delay=0.0):
        self.records_by_name = records_by_name or {}
        self.delay = delay
        self.calls = []
        self._lock = threading.Lock()

    def __call__(self, query):
        if self.delay:
            time.sleep(self.delay)
        q = query.questions[0]
        with self._lock:
            self.calls.append((q.qname, q.qtype))
        records = self.records_by_name.get(q.qname.lower(), [])
        return canned_response(query, records)

    @property
    def call_count(self):
        with self._lock:
            return len(self.calls)


def make_resolver(fake, clock=None):
    resolver = UpstreamResolver("192.0.2.53", port=53, timeout=0.5,
                                cache=DNSCache(clock=clock))
    resolver._exchange = fake
    return resolver


def query_for(name, qtype=P.TYPE_A):
    return make_query(name, qtype)


# ---------------------------------------------------------------- 转发 + 缓存

def test_forward_and_cache_hit():
    fake = FakeUpstream({"example.com": [a_rr("example.com", "1.2.3.4")]})
    resolver = make_resolver(fake)

    resp, hit = resolver.resolve(query_for("example.com"))
    assert not hit
    assert resp.rcode == P.RCODE_NOERROR
    assert resp.answers[0].rdata.address == "1.2.3.4"

    resp2, hit2 = resolver.resolve(query_for("example.com"))
    assert hit2  # 第二次走缓存，不再问上游
    assert resp2.answers[0].rdata.address == "1.2.3.4"
    assert fake.call_count == 1


def test_cache_ttl_expiry():
    class Clock:
        now = 1000.0
        def __call__(self):
            return self.now
    clock = Clock()
    fake = FakeUpstream({"example.com": [a_rr("example.com", "1.2.3.4", ttl=30)]})
    resolver = make_resolver(fake, clock=clock)

    resolver.resolve(query_for("example.com"))
    clock.now += 10
    _, hit = resolver.resolve(query_for("example.com"))
    assert hit  # 未过期
    clock.now += 25  # 总共 35s > TTL 30
    _, hit = resolver.resolve(query_for("example.com"))
    assert not hit  # 已过期，重新问上游
    assert fake.call_count == 2


def test_cache_key_separates_types():
    fake = FakeUpstream({"example.com": [a_rr("example.com", "1.2.3.4")]})
    resolver = make_resolver(fake)
    resolver.resolve(query_for("example.com", P.TYPE_A))
    _, hit = resolver.resolve(query_for("example.com", P.TYPE_AAAA))
    assert not hit  # AAAA 没缓存，单独问上游
    assert fake.call_count == 2


def test_cached_ttl_counts_down():
    fake = FakeUpstream({"example.com": [a_rr("example.com", "1.2.3.4", ttl=100)]})
    resolver = make_resolver(fake)
    resolver.resolve(query_for("example.com"))
    time.sleep(0.05)
    resp, hit = resolver.resolve(query_for("example.com"))
    assert hit
    assert resp.answers[0].ttl < 100


def test_upstream_failure_servfail():
    def boom(query):
        raise OSError("timeout")
    resolver = make_resolver(boom)
    resp, hit = resolver.resolve(query_for("example.com"))
    assert not hit
    assert resp.rcode == P.RCODE_SERVFAIL


def test_upstream_nxdomain_passed_through():
    fake = FakeUpstream({})  # 无记录 -> NOERROR 空应答
    resolver = make_resolver(fake)
    resp, _ = resolver.resolve(query_for("nosuch.example.com"))
    assert resp.rcode == P.RCODE_NOERROR
    assert resp.answers == []


def test_response_id_matches_client():
    fake = FakeUpstream({"example.com": [a_rr("example.com", "1.2.3.4")]})
    resolver = make_resolver(fake)
    query = query_for("example.com")
    query.id = 4242
    resp, _ = resolver.resolve(query)
    assert resp.id == 4242  # 用客户端的 ID，不是上游回包的 ID


# ---------------------------------------------------------------- singleflight

def test_singleflight_merges_concurrent_queries():
    barrier = threading.Barrier(9)  # 8 个客户端线程 + 主线程
    fake = FakeUpstream({"slow.example.com": [a_rr("slow.example.com", "9.9.9.9")]},
                        delay=0.3)
    resolver = make_resolver(fake)
    results = []
    errors = []

    def worker():
        try:
            barrier.wait(timeout=5)
            resp, _ = resolver.resolve(query_for("slow.example.com"))
            results.append(resp.answers[0].rdata.address)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    barrier.wait(timeout=5)
    for t in threads:
        t.join(timeout=15)
    assert not errors
    assert results == ["9.9.9.9"] * 8
    assert fake.call_count == 1  # 同一时刻只向上游发了一个请求


# ---------------------------------------------------------------- 真实网络集成

@requires_network
def test_real_upstream_over_udp():
    """起一个假上游 UDP 服务，验证真实报文收发 + 缓存。"""
    from minidns.server import DNSServer, QueryHandler

    upstream_zone_text = (
        "$ORIGIN remote.test.\n$TTL 1\n"
        "www IN A 203.0.113.7\n")
    import tempfile, os
    from minidns.zone import ZoneParser
    zone = ZoneParser(filename="u.zone").parse_text(upstream_zone_text)
    upstream = DNSServer(QueryHandler(zones=[zone]), host="127.0.0.1", port=0)
    upstream.start()

    resolver = UpstreamResolver("127.0.0.1", port=upstream.port, timeout=1.0)
    local = DNSServer(QueryHandler(zones=[], resolver=resolver),
                      host="127.0.0.1", port=0)
    local.start()
    try:
        q = make_query("www.remote.test", P.TYPE_A).encode()
        resp1 = P.Message.decode(udp_exchange(q, local.port))
        assert resp1.rcode == P.RCODE_NOERROR
        assert resp1.answers[0].rdata.address == "203.0.113.7"
        # TTL=1，等 1.2s 后缓存过期
        time.sleep(1.2)
        resp2 = P.Message.decode(udp_exchange(q, local.port))
        assert resp2.rcode == P.RCODE_NOERROR
    finally:
        local.shutdown()
        upstream.shutdown()


@requires_network
def test_real_upstream_timeout_servfail():
    """上游不应答（丢包 socket），超时后返回 SERVFAIL。"""
    import socket
    blackhole = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blackhole.bind(("127.0.0.1", 0))  # 收了包但从不回复
    port = blackhole.getsockname()[1]

    from minidns.server import DNSServer, QueryHandler
    resolver = UpstreamResolver("127.0.0.1", port=port, timeout=0.3)
    local = DNSServer(QueryHandler(zones=[], resolver=resolver),
                      host="127.0.0.1", port=0)
    local.start()
    try:
        resp = P.Message.decode(
            udp_exchange(make_query("lost.example", P.TYPE_A).encode(),
                         local.port))
        assert resp.rcode == P.RCODE_SERVFAIL
    finally:
        local.shutdown()
        blackhole.close()
