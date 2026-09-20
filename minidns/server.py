"""DNS 服务器：UDP/TCP 传输、权威应答、递归转发、访问日志。"""

import logging
import socket
import socketserver
import struct
import threading
import time

from . import protocol as P
from .zone import find_zone

logger = logging.getLogger("minidns")

UDP_MAX_PAYLOAD = 512  # 无 EDNS 的经典上限


# ---------------------------------------------------------------- 查询处理

class QueryHandler:
    """传输层无关的查询处理：bytes in -> bytes out。"""

    def __init__(self, zones=None, resolver=None):
        self.zones = zones or []
        self.resolver = resolver

    def process(self, data, client, via_tcp):
        """返回应答字节；报文无法辨认（连 ID 都取不到）时返回 None 直接丢弃。"""
        start = time.monotonic()
        qname = "-"
        qtype = "-"
        cache_hit = "-"
        try:
            query = P.Message.decode(data)
        except P.DNSError:
            # 尽量取出 ID 回 FORMERR；太短连 ID 都没有就丢弃
            if len(data) < 2:
                self._log(client, qname, qtype, "DROP", start, cache_hit)
                return None
            (qid,) = struct.unpack_from("!H", data, 0)
            resp = P.Message()
            resp.id = qid
            resp.qr = 1
            resp.rcode = P.RCODE_FORMERR
            self._log(client, qname, qtype, P.RCODE_FORMERR, start, cache_hit)
            return resp.encode()

        if query.questions:
            qname = query.questions[0].qname
            qtype = P.type_to_name(query.questions[0].qtype)

        resp = self._answer(query)
        if resp is None:
            self._log(client, qname, qtype, "DROP", start, cache_hit)
            return None

        cache_hit = getattr(resp, "_cache_hit", "-")
        payload = resp.encode()
        if not via_tcp and len(payload) > UDP_MAX_PAYLOAD:
            # UDP 放不下：置 TC=1，清空应答段，让客户端改走 TCP
            resp.tc = 1
            resp.answers = []
            resp.authorities = []
            resp.additionals = []
            payload = resp.encode()
        self._log(client, qname, qtype, resp.rcode, start, cache_hit)
        return payload

    def _answer(self, query):
        if query.qr != 0:
            return None  # 收到的是应答不是查询，丢弃
        if query.opcode != P.OPCODE_QUERY:
            return query.make_response(P.RCODE_NOTIMP)
        if not query.questions:
            return query.make_response(P.RCODE_FORMERR)

        question = query.questions[0]
        resp = self._answer_authoritative(query, question)
        if resp is not None:
            return resp
        if self.resolver is not None:
            resp, hit = self.resolver.resolve(query)
            resp._cache_hit = "HIT" if hit else "MISS"
            return resp
        return query.make_response(P.RCODE_REFUSED)

    def _answer_authoritative(self, query, question):
        qname = question.qname.lower()
        zone = find_zone(self.zones, qname)
        if zone is None:
            return None  # 不在我们的 zone 里，交给递归

        resp = query.make_response()
        resp.aa = 1

        current = qname
        current_zone = zone
        visited = {current}
        while True:
            by_type = current_zone.get_any(current)
            # 直接命中所查类型
            if question.qtype in by_type:
                resp.answers.extend(current_zone.get(current, question.qtype))
                return resp
            # CNAME：带上记录，继续跟链
            if P.TYPE_CNAME in by_type and question.qtype != P.TYPE_CNAME:
                cname_rr = current_zone.get(current, P.TYPE_CNAME)[0]
                resp.answers.append(cname_rr)
                target = cname_rr.rdata.name.lower()
                if target in visited:
                    # 配置成环了，按断链处理
                    resp.rcode = P.RCODE_NXDOMAIN
                    return resp
                visited.add(target)
                next_zone = find_zone(self.zones, target)
                if next_zone is None:
                    resp.rcode = P.RCODE_NXDOMAIN  # 链断了
                    return resp
                current = target
                current_zone = next_zone
                continue
            if by_type:
                return resp  # 名字存在但没这个类型：NODATA (NOERROR, 空 Answer)
            resp.rcode = P.RCODE_NXDOMAIN
            return resp

    @staticmethod
    def _log(client, qname, qtype, rcode, start, cache_hit):
        elapsed_ms = (time.monotonic() - start) * 1000.0
        if isinstance(rcode, int):
            rcode = P.rcode_to_name(rcode)
        logger.info("%s:%d %s %s %s %.1fms cache=%s",
                    client[0], client[1], qname, qtype, rcode,
                    elapsed_ms, cache_hit)


# ---------------------------------------------------------------- 传输层

class _ThreadingUDPServer(socketserver.ThreadingMixIn, socketserver.UDPServer):
    daemon_threads = True
    allow_reuse_address = True


class _ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


class _UDPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data, sock = self.request
        try:
            payload = self.server.query_handler.process(
                data, self.client_address, via_tcp=False)
        except Exception:
            logger.exception("udp handler error")
            return
        if payload is not None:
            sock.sendto(payload, self.client_address)


class _TCPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        conn = self.request
        conn.settimeout(30)
        try:
            while True:
                header = self._recv_exactly(2)
                if header is None:
                    return
                (length,) = struct.unpack("!H", header)
                data = self._recv_exactly(length)
                if data is None:
                    return
                try:
                    payload = self.server.query_handler.process(
                        data, self.client_address, via_tcp=True)
                except Exception:
                    logger.exception("tcp handler error")
                    return
                if payload is None:
                    return
                conn.sendall(len(payload).to_bytes(2, "big") + payload)
        except (ConnectionError, socket.error, struct.error):
            return

    def _recv_exactly(self, n):
        chunks = []
        remaining = n
        while remaining > 0:
            try:
                chunk = self.request.recv(remaining)
            except (ConnectionError, socket.error):
                return None
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


class DNSServer:
    """同时跑 UDP 和 TCP 的 DNS 服务器。"""

    def __init__(self, handler, host="", port=5353):
        self.handler = handler
        self.udp_server = _ThreadingUDPServer((host, port), _UDPHandler)
        # TCP 绑定到 UDP 实际拿到的端口（port=0 时两者一致）
        real_port = self.udp_server.server_address[1]
        self.tcp_server = _ThreadingTCPServer((host, real_port), _TCPHandler)
        self.udp_server.query_handler = handler
        self.tcp_server.query_handler = handler
        self._threads = []

    @property
    def port(self):
        return self.udp_server.server_address[1]

    def start(self):
        for srv in (self.udp_server, self.tcp_server):
            t = threading.Thread(target=srv.serve_forever,
                                 kwargs={"poll_interval": 0.1}, daemon=True)
            t.start()
            self._threads.append(t)

    def serve_forever(self):
        self.start()
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self):
        for srv in (self.udp_server, self.tcp_server):
            srv.shutdown()
            srv.server_close()
        for t in self._threads:
            t.join(timeout=2)
