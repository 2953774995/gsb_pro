"""minidns 命令行：serve（起服务）/ query（调试查询）。"""

import argparse
import logging
import random
import socket
import struct
import sys
import time

from . import protocol as P
from .resolver import UpstreamResolver
from .server import DNSServer, QueryHandler
from .zone import load_zone_dir


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="minidns", description="迷你 DNS 服务器（权威 + 递归转发 + 缓存）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="启动 DNS 服务")
    p_serve.add_argument("--zones", required=True, help="zone 文件目录")
    p_serve.add_argument("--port", type=int, default=5353, help="监听端口（默认 5353）")
    p_serve.add_argument("--host", default="", help="监听地址（默认全部）")
    p_serve.add_argument("--upstream", default=None,
                         help="上游 DNS（递归转发），如 223.5.5.5")
    p_serve.add_argument("--upstream-port", type=int, default=53)
    p_serve.add_argument("--timeout", type=float, default=3.0,
                         help="上游超时秒数（默认 3）")
    p_serve.add_argument("-v", "--verbose", action="store_true")

    p_query = sub.add_parser("query", help="发一个查询并打印应答")
    p_query.add_argument("--server", required=True, help="服务器 host:port")
    p_query.add_argument("name", help="查询名")
    p_query.add_argument("type", nargs="?", default="A", help="记录类型（默认 A）")
    p_query.add_argument("--tcp", action="store_true", help="直接用 TCP 查询")
    p_query.add_argument("--timeout", type=float, default=5.0)

    args = parser.parse_args(argv)
    if args.command == "serve":
        return _cmd_serve(args)
    if args.command == "query":
        return _cmd_query(args)
    return 2


# ---------------------------------------------------------------- serve

def _cmd_serve(args):
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("minidns")

    zones = load_zone_dir(args.zones)
    for zone in zones:
        n_records = sum(len(v) for v in zone.records.values())
        log.info("loaded zone %s (%d names, %d records)",
                 zone.origin or ".", len(zone.records), n_records)

    resolver = None
    if args.upstream:
        resolver = UpstreamResolver(args.upstream, port=args.upstream_port,
                                    timeout=args.timeout)
        log.info("recursive forwarding via %s:%d (timeout %.1fs)",
                 args.upstream, args.upstream_port, args.timeout)

    handler = QueryHandler(zones=zones, resolver=resolver)
    server = DNSServer(handler, host=args.host, port=args.port)
    log.info("minidns listening on %s:%d (udp+tcp)",
             args.host or "0.0.0.0", server.port)
    server.serve_forever()
    return 0


# ---------------------------------------------------------------- query

def _parse_server(text):
    if text.startswith("["):  # [v6]:port
        host, _, rest = text[1:].partition("]:")
        return host, int(rest)
    host, sep, port = text.rpartition(":")
    if not sep:
        return text, 5353
    return host, int(port)


def _cmd_query(args):
    try:
        qtype = P.name_to_type(args.type)
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    host, port = _parse_server(args.server)

    query = P.Message()
    query.id = random.randrange(0, 0x10000)
    query.rd = 1
    query.questions.append(P.Question(args.name, qtype, P.CLASS_IN))
    data = query.encode()

    start = time.monotonic()
    try:
        if args.tcp:
            raw = _query_tcp(host, port, data, args.timeout)
        else:
            raw = _query_udp(host, port, data, args.timeout)
            resp = P.Message.decode(raw)
            if resp.tc:
                print(";; truncated, retrying over TCP", file=sys.stderr)
                raw = _query_tcp(host, port, data, args.timeout)
    except (OSError, P.DNSError) as e:
        print(";; query failed: %s" % e, file=sys.stderr)
        return 1
    elapsed = (time.monotonic() - start) * 1000.0

    try:
        resp = P.Message.decode(raw)
    except P.DNSError as e:
        print(";; bad response: %s" % e, file=sys.stderr)
        return 1
    _print_message(resp, elapsed, (host, port))
    return 0 if resp.rcode == P.RCODE_NOERROR else 1


def _query_udp(host, port, data, timeout):
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(data, (host, port))
        raw, _ = sock.recvfrom(65535)
        return raw
    finally:
        sock.close()


def _query_tcp(host, port, data, timeout):
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.sendall(len(data).to_bytes(2, "big") + data)
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


def _print_message(msg, elapsed_ms, server):
    flags = []
    if msg.qr:
        flags.append("qr")
    if msg.aa:
        flags.append("aa")
    if msg.tc:
        flags.append("tc")
    if msg.rd:
        flags.append("rd")
    if msg.ra:
        flags.append("ra")
    print(";; ->>HEADER<<- opcode: QUERY, status: %s, id: %d"
          % (P.rcode_to_name(msg.rcode), msg.id))
    print(";; flags: %s; QUERY: %d, ANSWER: %d, AUTHORITY: %d, ADDITIONAL: %d"
          % (" ".join(flags), len(msg.questions), len(msg.answers),
             len(msg.authorities), len(msg.additionals)))
    print()
    if msg.questions:
        print(";; QUESTION SECTION:")
        for q in msg.questions:
            print(";%s.\t\tIN\t%s" % (q.qname, P.type_to_name(q.qtype)))
        print()
    for title, section in (("ANSWER", msg.answers),
                           ("AUTHORITY", msg.authorities),
                           ("ADDITIONAL", msg.additionals)):
        if section:
            print(";; %s SECTION:" % title)
            for rr in section:
                print("%s.\t%d\tIN\t%s\t%s"
                      % (rr.name, rr.ttl, P.type_to_name(rr.rtype), rr.rdata))
            print()
    print(";; Query time: %.1f ms" % elapsed_ms)
    print(";; SERVER: %s:%d" % server)


if __name__ == "__main__":
    sys.exit(main())
