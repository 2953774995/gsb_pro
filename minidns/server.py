"""DNS 服务器：UDP/TCP 传输、权威应答、递归转发（singleflight）、访问日志。"""

import random
import socket
import struct
import sys
import threading
import time

from .cache import Cache
from .protocol import (CLASS_IN, DNSFormatError, Header, Message, Question,
                       RCODE_FORMERR, RCODE_NOERROR, RCODE_NOTIMP,
                       RCODE_SERVFAIL, rcode_to_str, type_to_str)
from .zone import ZoneStore

UDP_MAX_PAYLOAD = 512  # 不支持 EDNS，UDP 应答超过 512 字节就截断置 TC


class UpstreamError(Exception):
    """上游查询失败（超时/网络错误）。"""


class UpstreamResolver(object):
    """递归转发器：把查询发给上游，带 singleflight 合并相同并发查询。"""

    def __init__(self, upstream, port=53, timeout=3.0):
        self.upstream = upstream
        self.port = port
        self.timeout = timeout
        self._lock = threading.Lock()
        self._inflight = {}  # key -> _Flight

    def resolve(self, qname, qtype, qclass=CLASS_IN):
        key = (qname, qtype, qclass)
        with self._lock:
            flight = self._inflight.get(key)
            if flight is None:
                flight = _Flight()
                self._inflight[key] = flight
                owner = True
            else:
                owner = False
        if owner:
            try:
                flight.result = self._query_upstream(qname, qtype, qclass)
            except Exception as exc:  # noqa: BLE001 - 任何失败都转成 SERVFAIL
                flight.error = exc
            finally:
                with self._lock:
                    self._inflight.pop(key, None)
                flight.event.set()
        else:
            flight.event.wait()
        if flight.error is not None:
            raise UpstreamError(str(flight.error))
        return flight.result

    def _query_upstream(self, qname, qtype, qclass):
        query = Message(Header(id=random.randint(0, 0xFFFF), rd=1))
        query.questions.append(Question(qname, qtype, qclass))
        payload = query.to_bytes()
        family = socket.AF_INET6 if ':' in self.upstream else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_DGRAM)
        try:
            sock.settimeout(self.timeout)
            sock.sendto(payload, (self.upstream, self.port))
            data, _ = sock.recvfrom(65535)
        except socket.timeout:
            raise UpstreamError('upstream %s timed out' % self.upstream)
        finally:
            sock.close()
        resp = Message.parse(data)
        if resp.header.id != query.header.id:
            raise UpstreamError('upstream response id mismatch')
        return resp


class _Flight(object):
    def __init__(self):
        self.event = threading.Event()
        self.result = None
        self.error = None


class DNSServer(object):
    def __init__(self, zone_store=None, upstream=None, upstream_port=53,
                 host='127.0.0.1', port=5353, timeout=3.0,
                 cache=None, log_file=None):
        self.zones = zone_store or ZoneStore()
        self.upstream = (UpstreamResolver(upstream, upstream_port, timeout)
                         if upstream else None)
        self.cache = cache if cache is not None else Cache()
        self.host = host
        self.port = port
        self.log_file = log_file if log_file is not None else sys.stdout
        self._log_lock = threading.Lock()
        self._stopping = threading.Event()
        self.udp_sock = None
        self.tcp_sock = None
        self._threads = []

    # ------------------------------------------------------------------
    # 查询处理（与传输层无关）
    # ------------------------------------------------------------------

    def handle_query(self, data, client='?'):
        """处理一条原始查询报文，返回应答字节；无法应答时返回 None（丢弃）。"""
        start = time.time()
        qname, qtype = '?', '?'
        rcode = RCODE_SERVFAIL
        cache_flag = '-'
        try:
            try:
                msg = Message.parse(data)
            except DNSFormatError:
                if len(data) < 12:
                    return None  # 连 ID 都拿不到，直接丢弃
                qid = struct.unpack('!H', data[:2])[0]
                rcode = RCODE_FORMERR
                resp = Message(Header(id=qid, qr=1, rcode=RCODE_FORMERR))
                return resp.to_bytes()
            if msg.header.qr:
                return None  # 收到的是应答报文，忽略
            if not msg.questions:
                rcode = RCODE_FORMERR
                return Message(Header(id=msg.header.id, qr=1,
                                      rcode=RCODE_FORMERR)).to_bytes()
            q = msg.questions[0]
            qname, qtype = q.qname, type_to_str(q.qtype)
            try:
                resp, rcode, cache_flag = self._answer(msg, q)
                return resp.to_bytes()
            except Exception:  # noqa: BLE001 - 任何内部错误都不能拖垮服务
                rcode = RCODE_SERVFAIL
                return Message(Header(id=msg.header.id, qr=1,
                                      rcode=RCODE_SERVFAIL)).to_bytes()
        finally:
            self._log(client, qname, qtype, rcode, start, cache_flag)

    def _answer(self, msg, q):
        """返回 (应答 Message, rcode, cache_flag)。"""
        header = Header(id=msg.header.id, qr=1, rd=msg.header.rd)
        resp = Message(header)
        resp.questions = list(msg.questions)

        if msg.header.opcode != 0:
            header.rcode = RCODE_NOTIMP
            return resp, RCODE_NOTIMP, '-'

        result = self.zones.lookup(q.qname, q.qtype)
        if result is not None:
            rcode, answers = result
            header.rcode = rcode
            header.aa = 1
            header.ra = 1 if self.upstream else 0
            resp.answers = answers
            return resp, rcode, '-'

        # 非权威：走缓存 / 递归转发
        header.ra = 1
        if self.upstream is None:
            header.rcode = RCODE_SERVFAIL
            return resp, RCODE_SERVFAIL, '-'
        cached = self.cache.get(q.qname, q.qtype, q.qclass)
        if cached is not None:
            resp.answers = cached
            return resp, RCODE_NOERROR, 'HIT'
        try:
            upstream_resp = self.upstream.resolve(q.qname, q.qtype, q.qclass)
        except UpstreamError:
            header.rcode = RCODE_SERVFAIL
            return resp, RCODE_SERVFAIL, 'MISS'
        # 缓存上游回答里的记录
        self.cache.put_records(upstream_resp.answers)
        # 把上游应答原样转回（重写 ID 以匹配客户端查询）
        upstream_resp.header.id = msg.header.id
        upstream_resp.header.rd = msg.header.rd
        upstream_resp.header.ra = 1
        return upstream_resp, upstream_resp.header.rcode, 'MISS'

    # ------------------------------------------------------------------
    # 传输层
    # ------------------------------------------------------------------

    def start(self):
        """绑定端口并后台启动 UDP/TCP 服务。port=0 时自动分配。幂等：重复调用只绑一次。"""
        if self._threads:
            return self.port
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_sock.bind((self.host, self.port))
        self.port = self.udp_sock.getsockname()[1]

        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_sock.bind((self.host, self.port))
        self.tcp_sock.listen(64)

        for target in (self._udp_loop, self._tcp_loop):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)
        return self.port

    def serve_forever(self):
        self.start()
        try:
            while not self._stopping.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self):
        self._stopping.set()
        for sock in (self.udp_sock, self.tcp_sock):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    def _udp_loop(self):
        while not self._stopping.is_set():
            try:
                data, addr = self.udp_sock.recvfrom(65535)
            except OSError:
                break
            threading.Thread(target=self._handle_udp, args=(data, addr),
                             daemon=True).start()

    def _handle_udp(self, data, addr):
        client = '%s:%d' % addr[:2]
        resp = self.handle_query(data, client)
        if resp is None:
            return
        if len(resp) > UDP_MAX_PAYLOAD:
            resp = truncate_message(resp)
            if resp is None:
                return
        try:
            self.udp_sock.sendto(resp, addr)
        except OSError:
            pass

    def _tcp_loop(self):
        while not self._stopping.is_set():
            try:
                conn, addr = self.tcp_sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle_tcp_conn,
                             args=(conn, addr), daemon=True).start()

    def _handle_tcp_conn(self, conn, addr):
        client = '%s:%d' % addr[:2]
        try:
            conn.settimeout(30)
            while not self._stopping.is_set():
                hdr = _recv_exact(conn, 2)
                if hdr is None:
                    break
                (length,) = struct.unpack('!H', hdr)
                if length == 0:
                    break
                data = _recv_exact(conn, length)
                if data is None:
                    break
                resp = self.handle_query(data, client)
                if resp is not None:
                    conn.sendall(struct.pack('!H', len(resp)) + resp)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    # ------------------------------------------------------------------

    def _log(self, client, qname, qtype, rcode, start, cache_flag):
        elapsed_ms = (time.time() - start) * 1000.0
        line = '%s %s %s %s %s %.1fms cache=%s' % (
            time.strftime('%Y-%m-%d %H:%M:%S'), client, qname, qtype,
            rcode_to_str(rcode), elapsed_ms, cache_flag)
        with self._log_lock:
            try:
                self.log_file.write(line + '\n')
                self.log_file.flush()
            except (OSError, ValueError):
                pass


def _recv_exact(conn, n):
    buf = b''
    while len(buf) < n:
        try:
            chunk = conn.recv(n - len(buf))
        except socket.timeout:
            return None
        if not chunk:
            return None
        buf += chunk
    return buf


def truncate_message(data):
    """UDP 应答超过 512 字节时：置 TC=1、清空 Answer/Authority/Additional。

    客户端看到 TC=1 应改走 TCP 重新查询。解析失败返回 None。
    """
    try:
        msg = Message.parse(data)
    except DNSFormatError:
        return None
    msg.header.tc = 1
    msg.answers = []
    msg.authorities = []
    msg.additionals = []
    return msg.to_bytes()
