"""递归解析：转发上游 DNS + TTL 缓存 + singleflight 合并。"""

import random
import socket
import struct
import threading

from . import protocol as P
from .cache import DNSCache


class _Flight:
    """一次正在进行的上游查询，其他相同 key 的请求等它出结果。"""

    def __init__(self):
        self.event = threading.Event()
        self.response = None  # Message 或 None（失败）


class UpstreamResolver:
    def __init__(self, upstream, port=53, timeout=3.0, cache=None):
        self.upstream = upstream
        self.port = port
        self.timeout = timeout
        self.cache = cache if cache is not None else DNSCache()
        self._lock = threading.Lock()
        self._inflight = {}  # key -> _Flight

    # ---- 对外入口 ----

    def resolve(self, query):
        """处理一个查询报文，返回 (应答 Message, 是否缓存命中)。

        上游失败时返回 rcode=SERVFAIL 的应答。
        """
        question = query.questions[0]
        key = DNSCache.make_key(question.qname, question.qtype, question.qclass)

        cached = self.cache.get(key)
        if cached is not None:
            resp = query.make_response()
            resp.ra = 1
            resp.answers = cached
            return resp, True

        flight, leader = self._start_flight(key)
        if leader:
            try:
                upstream_resp = self._exchange(query)
            except Exception:
                upstream_resp = None
            if upstream_resp is not None:
                self.cache.put_message(upstream_resp)
            with self._lock:
                self._inflight.pop(key, None)
            flight.response = upstream_resp
            flight.event.set()
        else:
            # 等第一个请求出结果；超时兜底自己查不了，直接失败
            flight.event.wait(self.timeout + 1.0)

        upstream_resp = flight.response
        if upstream_resp is None:
            resp = query.make_response(P.RCODE_SERVFAIL)
            resp.ra = 1
            return resp, False

        # 用客户端的 ID 和 Question 重新包装上游应答
        resp = query.make_response(upstream_resp.rcode)
        resp.ra = 1
        resp.answers = list(upstream_resp.answers)
        resp.authorities = list(upstream_resp.authorities)
        resp.additionals = list(upstream_resp.additionals)
        return resp, False

    def _start_flight(self, key):
        with self._lock:
            flight = self._inflight.get(key)
            if flight is not None:
                return flight, False
            flight = _Flight()
            self._inflight[key] = flight
            return flight, True

    # ---- 与上游通信 ----

    def _exchange(self, query):
        """把查询发给上游，返回上游应答 Message；超时/出错抛异常。"""
        fwd = P.Message()
        fwd.id = random.randrange(0, 0x10000)
        fwd.rd = 1
        fwd.questions = list(query.questions)
        data = fwd.encode()

        family = socket.AF_INET6 if ":" in self.upstream else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_DGRAM)
        try:
            sock.settimeout(self.timeout)
            sock.sendto(data, (self.upstream, self.port))
            raw, _ = sock.recvfrom(65535)
        finally:
            sock.close()
        resp = P.Message.decode(raw)
        if resp.id != fwd.id:
            raise OSError("upstream response id mismatch")
        if resp.tc:
            resp = self._exchange_tcp(data, fwd.id)
        return resp

    def _exchange_tcp(self, data, expect_id):
        family = socket.AF_INET6 if ":" in self.upstream else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            sock.connect((self.upstream, self.port))
            sock.sendall(len(data).to_bytes(2, "big") + data)
            header = _recv_exactly(sock, 2)
            (length,) = struct.unpack("!H", header)
            raw = _recv_exactly(sock, length)
        finally:
            sock.close()
        resp = P.Message.decode(raw)
        if resp.id != expect_id:
            raise OSError("upstream tcp response id mismatch")
        return resp


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
