"""命令行入口：minidns serve / minidns query。"""

import argparse
import random
import socket
import struct
import sys
import time

from .protocol import (Message, make_query, rcode_to_str, type_from_str,
                       type_to_str)
from .server import DNSServer
from .zone import ZoneStore, ZoneParseError


def _cmd_serve(args):
    store = ZoneStore()
    if args.zones:
        try:
            loaded = store.load_dir(args.zones)
        except ZoneParseError as exc:
            print('zone 文件解析失败: %s' % exc, file=sys.stderr)
            return 1
        for zone in loaded:
            print('loaded zone %s (%d 个名字)' %
                  (zone.origin, len(zone._names)))
    server = DNSServer(zone_store=store, upstream=args.upstream,
                       host=args.host, port=args.port,
                       timeout=args.timeout)
    port = server.start()
    print('minidns listening on %s:%d (UDP+TCP)%s' % (
        args.host, port,
        ', upstream=%s' % args.upstream if args.upstream else ''))
    server.serve_forever()
    return 0


def _print_section(title, records):
    if not records:
        return
    print(';; %s:' % title)
    for rec in records:
        print('%s\t%d\tIN\t%s\t%s' % (
            rec.name, rec.ttl, type_to_str(rec.type), rec.rdata_to_text()))


def _cmd_query(args):
    server = args.server
    port = args.port
    if ':' in server:
        server, p = server.rsplit(':', 1)
        port = int(p)
    try:
        qtype = type_from_str(args.type)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    query = make_query(args.name, qtype, qid=random.randint(0, 0xFFFF))
    payload = query.to_bytes()
    start = time.time()
    resp = None
    used_tcp = args.tcp
    if not args.tcp:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(args.timeout)
            sock.sendto(payload, (server, port))
            data, _ = sock.recvfrom(65535)
            resp = Message.parse(data)
        except socket.timeout:
            print(';; UDP 查询超时', file=sys.stderr)
            return 1
        finally:
            sock.close()
        if resp.header.tc:
            print(';; UDP 应答被截断 (TC=1)，改用 TCP 重试')
            used_tcp = True
            resp = None
    if used_tcp:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(args.timeout)
            sock.connect((server, port))
            sock.sendall(struct.pack('!H', len(payload)) + payload)
            hdr = _recv_exact(sock, 2)
            if hdr is None:
                print(';; TCP 连接被关闭', file=sys.stderr)
                return 1
            (length,) = struct.unpack('!H', hdr)
            data = _recv_exact(sock, length)
            if data is None:
                print(';; TCP 应答不完整', file=sys.stderr)
                return 1
            resp = Message.parse(data)
        except socket.timeout:
            print(';; TCP 查询超时', file=sys.stderr)
            return 1
        finally:
            sock.close()
    elapsed_ms = (time.time() - start) * 1000.0

    h = resp.header
    flags = []
    for name in ('qr', 'aa', 'tc', 'rd', 'ra'):
        if getattr(h, name):
            flags.append(name)
    print(';; ->>HEADER<<- opcode: %s, status: %s, id: %d' % (
        'QUERY' if h.opcode == 0 else h.opcode, rcode_to_str(h.rcode), h.id))
    print(';; flags: %s; QUERY: %d, ANSWER: %d, AUTHORITY: %d, ADDITIONAL: %d'
          % (' '.join(flags) or '-', len(resp.questions), len(resp.answers),
             len(resp.authorities), len(resp.additionals)))
    if resp.questions:
        print(';; QUESTION:')
        for q in resp.questions:
            print(';%s\tIN\t%s' % (q.qname, type_to_str(q.qtype)))
    _print_section('ANSWER', resp.answers)
    _print_section('AUTHORITY', resp.authorities)
    _print_section('ADDITIONAL', resp.additionals)
    print(';; Query time: %.1f ms (%s)' % (elapsed_ms,
                                           'TCP' if used_tcp else 'UDP'))
    return 0 if h.rcode == 0 else 1


def _recv_exact(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='minidns', description='纯标准库迷你 DNS 服务器')
    sub = parser.add_subparsers(dest='command', required=True)

    p_serve = sub.add_parser('serve', help='启动 DNS 服务（UDP+TCP）')
    p_serve.add_argument('--zones', help='zone 文件目录')
    p_serve.add_argument('--host', default='0.0.0.0')
    p_serve.add_argument('--port', type=int, default=5353)
    p_serve.add_argument('--upstream', help='上游 DNS（递归转发用）')
    p_serve.add_argument('--timeout', type=float, default=3.0,
                         help='上游超时秒数（默认 3）')
    p_serve.set_defaults(func=_cmd_serve)

    p_query = sub.add_parser('query', help='发一个查询并打印应答（调试用）')
    p_query.add_argument('--server', default='127.0.0.1',
                         help='服务器地址，可带端口 host:port')
    p_query.add_argument('--port', type=int, default=5353)
    p_query.add_argument('--tcp', action='store_true', help='直接走 TCP')
    p_query.add_argument('--timeout', type=float, default=3.0)
    p_query.add_argument('name')
    p_query.add_argument('type', nargs='?', default='A')
    p_query.set_defaults(func=_cmd_query)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
