"""递归转发 + 缓存 + singleflight（用进程内假上游，不依赖网络）。"""

import threading
import time

import pytest

from minidns.protocol import (CLASS_IN, TYPE_A, TYPE_TXT, Header, Message,
                              Question, RCODE_NOERROR, RCODE_SERVFAIL, Record)
from minidns.server import DNSServer, UpstreamError, UpstreamResolver
from minidns.zone import ZoneStore


class FakeUpstream(object):
    """进程内假上游：替换 UpstreamResolver._query_upstream。"""

    def __init__(self, answers=None, delay=0.0, fail=False):
        self.answers = answers or {}
        self.delay = delay
        self.fail = fail
        self.request_count = 0
        self._lock = threading.Lock()

    def __call__(self, qname, qtype, qclass=CLASS_IN):
        with self._lock:
            self.request_count += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise UpstreamError('fake upstream failure')
        resp = Message(Header(id=1234, qr=1, rd=1, ra=1, rcode=RCODE_NOERROR))
        resp.questions.append(Question(qname, qtype, qclass))
        resp.answers = [Record(qname, qtype, CLASS_IN, 60, rdata)
                        for rdata in self.answers.get((qname, qtype), [])]
        return resp


def make_server(fake):
    server = DNSServer(zone_store=ZoneStore(), upstream='192.0.2.1',
                       host='127.0.0.1', port=0)
    server.upstream._query_upstream = fake  # 注入假上游，不走网络
    return server


def query(server, name, qtype, qid=1):
    q = Message(Header(id=qid, rd=1))
    q.questions.append(Question(name, qtype))
    return Message.parse(server.handle_query(q.to_bytes(), 'test'))


def test_recursive_forward_and_cache():
    fake = FakeUpstream({('www.remote.test.', TYPE_A): ['93.184.216.34']})
    server = make_server(fake)
    r1 = query(server, 'www.remote.test', TYPE_A, qid=11)
    assert r1.header.id == 11  # ID 已改写成客户端的
    assert r1.header.qr == 1 and r1.header.ra == 1
    assert r1.answers[0].rdata == '93.184.216.34'
    assert fake.request_count == 1

    # 第二次命中缓存，不再问上游
    r2 = query(server, 'www.remote.test', TYPE_A, qid=22)
    assert r2.header.id == 22
    assert r2.answers[0].rdata == '93.184.216.34'
    assert fake.request_count == 1
    assert 0 < r2.answers[0].ttl <= 60


def test_cache_separated_by_type_recursive():
    fake = FakeUpstream({('www.remote.test.', TYPE_A): ['1.1.1.1']})
    server = make_server(fake)
    query(server, 'www.remote.test', TYPE_A)
    query(server, 'www.remote.test', TYPE_TXT)  # 同名字不同类型，不混缓存
    assert fake.request_count == 2


def test_upstream_failure_gives_servfail():
    fake = FakeUpstream(fail=True)
    server = make_server(fake)
    resp = query(server, 'lost.remote.test', TYPE_A)
    assert resp.header.rcode == RCODE_SERVFAIL


def test_singleflight_merges_concurrent_queries():
    fake = FakeUpstream({('slow.remote.test.', TYPE_A): ['8.8.8.8']}, delay=0.3)
    server = make_server(fake)
    results = []

    def worker(i):
        results.append(query(server, 'slow.remote.test', TYPE_A,
                             qid=100 + i).answers[0].rdata)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == ['8.8.8.8'] * 6
    # 6 个并发客户端只触发了 1 次上游请求
    assert fake.request_count == 1


def test_upstream_resolver_timeout():
    # 指到没人监听的端口，应超时抛 UpstreamError（需要能发 UDP，沙箱里跳过）
    resolver = UpstreamResolver('127.0.0.1', port=1, timeout=0.2)
    try:
        resolver.resolve('x.example.com.', TYPE_A)
    except UpstreamError:
        return
    except PermissionError:
        pytest.skip('sandbox 禁止 UDP')
    raise AssertionError('应该抛 UpstreamError')
