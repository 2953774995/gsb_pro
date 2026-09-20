"""BIND 风格 zone 文件解析 + Zone 数据结构和权威应答。

支持：$ORIGIN、$TTL、相对名字、@ 简写、行尾 ; 注释、括号多行续行、
引号包裹的 TXT 字符串、TTL 单位后缀（s/m/h/d/w）。
"""

import os
import socket
import threading

from . import protocol as P


class ZoneError(Exception):
    """zone 文件解析错误，带文件名和行号。"""

    def __init__(self, filename, lineno, message):
        self.filename = filename
        self.lineno = lineno
        where = filename or "<zone>"
        if lineno:
            where += ":%d" % lineno
        super().__init__("%s: %s" % (where, message))


# ---------------------------------------------------------------- 词法

def _scan_line(line, lineno, filename):
    """把一行切成 token 列表。

    处理：; 注释、( ) 独立成 token、"..." 引号字符串（保留空格，支持 \\ 转义）。
    """
    tokens = []
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c in " \t":
            i += 1
            continue
        if c == ";":
            break
        if c in "()":
            tokens.append(c)
            i += 1
            continue
        if c == '"':
            j = i + 1
            buf = []
            while j < n and line[j] != '"':
                if line[j] == "\\" and j + 1 < n:
                    buf.append(line[j + 1])
                    j += 2
                else:
                    buf.append(line[j])
                    j += 1
            if j >= n:
                raise ZoneError(filename, lineno, "unterminated quoted string")
            tokens.append(buf and "".join(buf) or "")
            i = j + 1
            continue
        j = i
        while j < n and line[j] not in ' \t;()"':
            j += 1
        tokens.append(line[i:j])
        i = j
    return tokens


def _logical_entries(text, filename):
    """把全文切成逻辑条目（括号续行合并）。

    返回 [(tokens, start_lineno, leading_whitespace), ...]
    """
    entries = []
    tokens = []
    start_line = None
    leading_ws = False
    depth = 0
    for lineno, raw in enumerate(text.splitlines(), 1):
        if not tokens and depth == 0 and not raw.strip():
            continue
        if not tokens and depth == 0:
            start_line = lineno
            leading_ws = raw[:1] in (" ", "\t")
        for tok in _scan_line(raw, lineno, filename):
            if tok == "(":
                depth += 1
                continue
            if tok == ")":
                depth -= 1
                if depth < 0:
                    raise ZoneError(filename, lineno, "unbalanced ')'")
                continue
            tokens.append(tok)
        if depth == 0 and tokens:
            entries.append((tokens, start_line, leading_ws))
            tokens = []
    if depth != 0:
        raise ZoneError(filename, start_line, "unbalanced '('")
    if tokens:
        entries.append((tokens, start_line, leading_ws))
    return entries


# ---------------------------------------------------------------- 语法

_TTL_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_ttl(token, filename, lineno):
    """解析 TTL：纯数字秒，或带单位后缀（如 1h、30m、1d）。"""
    text = token.lower()
    if text.isdigit():
        return int(text)
    if len(text) > 1 and text[:-1].isdigit() and text[-1] in _TTL_UNITS:
        return int(text[:-1]) * _TTL_UNITS[text[-1]]
    raise ZoneError(filename, lineno, "bad TTL: %r" % token)


def _looks_like_ttl(token):
    text = token.lower()
    return text.isdigit() or (
        len(text) > 1 and text[:-1].isdigit() and text[-1] in _TTL_UNITS)


def absolutize(name, origin):
    """把 zone 文件里的名字转成绝对名（小写、无尾点）。

    @ 表示 origin；以 . 结尾的是绝对名；其余拼上 origin。
    """
    if name == "@":
        if not origin:
            raise ValueError("@ used without $ORIGIN")
        return origin
    if name.endswith("."):
        return name[:-1].lower()
    if origin:
        return (name + "." + origin).lower()
    return name.lower()


def _parse_rdata(rtype, tokens, origin, filename, lineno):
    def need(n):
        if len(tokens) < n:
            raise ZoneError(filename, lineno,
                            "%s record needs %d rdata fields, got %d"
                            % (P.type_to_name(rtype), n, len(tokens)))

    if rtype == P.TYPE_A:
        need(1)
        try:
            socket.inet_pton(socket.AF_INET, tokens[0])
        except OSError:
            raise ZoneError(filename, lineno, "bad IPv4 address: %r" % tokens[0])
        return P.ARecord(tokens[0])
    if rtype == P.TYPE_AAAA:
        need(1)
        try:
            socket.inet_pton(socket.AF_INET6, tokens[0])
        except OSError:
            raise ZoneError(filename, lineno, "bad IPv6 address: %r" % tokens[0])
        return P.AAAARecord(tokens[0])
    if rtype == P.TYPE_NS:
        need(1)
        return P.NSRecord(absolutize(tokens[0], origin))
    if rtype == P.TYPE_CNAME:
        need(1)
        return P.CNAMERecord(absolutize(tokens[0], origin))
    if rtype == P.TYPE_MX:
        need(2)
        if not tokens[0].isdigit():
            raise ZoneError(filename, lineno, "bad MX preference: %r" % tokens[0])
        return P.MXRecord(int(tokens[0]), absolutize(tokens[1], origin))
    if rtype == P.TYPE_TXT:
        need(1)
        return P.TXTRecord(tokens)
    if rtype == P.TYPE_SOA:
        need(7)
        nums = []
        for tok in tokens[2:7]:
            if not tok.isdigit():
                raise ZoneError(filename, lineno, "bad SOA number: %r" % tok)
            nums.append(int(tok))
        return P.SOARecord(absolutize(tokens[0], origin),
                           absolutize(tokens[1], origin), *nums)
    raise ZoneError(filename, lineno,
                    "unsupported record type %s in zone file"
                    % P.type_to_name(rtype))


class Zone:
    """一个权威 zone：按 (名字, 类型) 存记录，同名多条做轮询。"""

    def __init__(self, origin):
        self.origin = origin  # 小写、无尾点
        self.records = {}     # name -> {rtype: [ResourceRecord]}
        self._counters = {}   # (name, rtype) -> 轮询计数
        self._lock = threading.Lock()

    def add(self, rr):
        name = rr.name.lower()
        self.records.setdefault(name, {}).setdefault(rr.rtype, []).append(rr)

    def has_name(self, name):
        return name.lower() in self.records

    def get(self, name, rtype):
        """取 (name, rtype) 的记录；多条时按轮询轮换起始位置。"""
        name = name.lower()
        rrs = self.records.get(name, {}).get(rtype)
        if not rrs:
            return []
        if len(rrs) == 1:
            return list(rrs)
        with self._lock:
            n = self._counters.get((name, rtype), 0)
            self._counters[(name, rtype)] = n + 1
        n %= len(rrs)
        return rrs[n:] + rrs[:n]

    def get_any(self, name):
        return self.records.get(name.lower(), {})

    def __repr__(self):
        return "Zone(%r, %d names)" % (self.origin, len(self.records))


class ZoneParser:
    def __init__(self, filename=None, default_origin="", default_ttl=3600):
        self.filename = filename
        self.origin = default_origin
        self.ttl = default_ttl
        self.last_name = None

    def parse_text(self, text):
        zone = Zone(self.origin)
        for tokens, lineno, leading_ws in _logical_entries(text, self.filename):
            self._parse_entry(zone, tokens, lineno, leading_ws)
        zone.origin = self.origin
        return zone

    def _parse_entry(self, zone, tokens, lineno, leading_ws):
        head = tokens[0].upper()
        if head.startswith("$"):
            self._parse_directive(tokens, lineno)
            return

        idx = 0
        if leading_ws:
            if self.last_name is None:
                raise ZoneError(self.filename, lineno,
                                "record without owner name (no previous name)")
            name = self.last_name
        else:
            name = tokens[0]
            idx = 1
            self.last_name = name

        ttl = self.ttl
        rclass = P.CLASS_IN
        # 可选的 TTL 和 CLASS，顺序任意
        for _ in range(2):
            if idx < len(tokens) and _looks_like_ttl(tokens[idx]):
                ttl = parse_ttl(tokens[idx], self.filename, lineno)
                idx += 1
            elif idx < len(tokens) and tokens[idx].upper() in ("IN", "CH", "HS"):
                if tokens[idx].upper() != "IN":
                    raise ZoneError(self.filename, lineno,
                                    "only class IN is supported")
                idx += 1
            else:
                break
        if idx >= len(tokens):
            raise ZoneError(self.filename, lineno, "missing record type")
        type_token = tokens[idx].upper()
        idx += 1
        try:
            rtype = P.name_to_type(type_token)
        except ValueError:
            raise ZoneError(self.filename, lineno,
                            "unknown record type: %r" % type_token)
        rdata = _parse_rdata(rtype, tokens[idx:], self.origin,
                             self.filename, lineno)
        try:
            absname = absolutize(name, self.origin)
        except ValueError as e:
            raise ZoneError(self.filename, lineno, str(e))
        zone.add(P.ResourceRecord(absname, rtype, rclass, ttl, rdata))

    def _parse_directive(self, tokens, lineno):
        directive = tokens[0].upper()
        if directive == "$ORIGIN":
            if len(tokens) != 2:
                raise ZoneError(self.filename, lineno, "$ORIGIN needs 1 argument")
            self.origin = tokens[1].rstrip(".").lower()
        elif directive == "$TTL":
            if len(tokens) != 2:
                raise ZoneError(self.filename, lineno, "$TTL needs 1 argument")
            self.ttl = parse_ttl(tokens[1], self.filename, lineno)
        else:
            raise ZoneError(self.filename, lineno,
                            "unknown directive: %r" % tokens[0])


def load_zone_file(path, default_origin=None):
    if default_origin is None:
        # 从文件名推导默认 origin：example.com.zone -> example.com
        base = os.path.basename(path)
        default_origin = base[:-5] if base.endswith(".zone") else base
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    parser = ZoneParser(filename=path, default_origin=default_origin.lower())
    return parser.parse_text(text)


def load_zone_dir(path):
    """加载目录下全部 zone 文件，按 origin 长度降序（最长后缀优先匹配）。"""
    zones = []
    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        if os.path.isfile(full) and not name.startswith("."):
            zones.append(load_zone_file(full))
    zones.sort(key=lambda z: len(z.origin), reverse=True)
    return zones


def find_zone(zones, qname):
    """找 qname 所属的最长后缀匹配 zone；找不到返回 None。"""
    qname = qname.lower()
    for zone in zones:
        origin = zone.origin
        if qname == origin or qname.endswith("." + origin) or not origin:
            return zone
    return None
