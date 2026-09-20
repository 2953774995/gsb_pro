"""BIND 风格 zone 文件解析 + 权威区域存储（轮询、CNAME 链）。

支持的指令与语法：
    $ORIGIN example.com.   /  $TTL 300
    @           IN  A       1.2.3.4
    www         300 IN  A   1.2.3.5   ; 行尾注释
    mail        IN  MX  10  mail.example.com.
    txt         IN  TXT "hello" (     ; 括号续行
                        "world" )
    行首留空表示沿用上一个 owner 名字。
"""

import os
import threading

from .protocol import (CLASS_IN, RCODE_NOERROR, RCODE_NXDOMAIN, RCODE_SERVFAIL,
                       TYPE_A, TYPE_AAAA, TYPE_CNAME, TYPE_MX, TYPE_NS,
                       TYPE_SOA, TYPE_TXT, TYPES, Record, normalize_name)


class ZoneParseError(Exception):
    def __init__(self, msg, filename, lineno):
        self.filename = filename
        self.lineno = lineno
        super(ZoneParseError, self).__init__(
            '%s:%d: %s' % (filename, lineno, msg))


_CLASSES = ('IN', 'CH', 'HS')


def _strip_comment(line):
    """去掉 ; 之后的注释，双引号内的 ; 不算注释。"""
    out = []
    in_quote = False
    for ch in line:
        if ch == '"':
            in_quote = not in_quote
            out.append(ch)
        elif ch == ';' and not in_quote:
            break
        else:
            out.append(ch)
    return ''.join(out)


def _split_tokens(line):
    """按空白切词，双引号内是一个整体（返回时去掉引号）。"""
    tokens = []
    cur = []
    in_quote = False
    for ch in line:
        if ch == '"':
            in_quote = not in_quote
        elif ch.isspace() and not in_quote:
            if cur:
                tokens.append(''.join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        tokens.append(''.join(cur))
    return tokens


def _logical_lines(text, filename):
    """把物理行合并成逻辑行（处理括号续行）。

    yield (起始行号, 行首是否有空白, 合并后的行文本)。
    """
    buf = ''
    start = None
    leading_ws = False
    depth = 0
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw)
        if start is None:
            if not line.strip():
                continue
            start = lineno
            leading_ws = raw[:1].isspace()
        depth += line.count('(') - line.count(')')
        if depth < 0:
            raise ZoneParseError("unbalanced ')'", filename, lineno)
        buf += ' ' + line.replace('(', ' ').replace(')', ' ')
        if depth == 0:
            yield start, leading_ws, buf
            buf = ''
            start = None
    if start is not None:
        raise ZoneParseError("unbalanced '('", filename, start)


def absolute(name, origin, filename, lineno):
    """把 zone 文件里的名字转成绝对名：@=origin，带点的绝对名原样，其余拼 origin。"""
    if name == '@':
        if origin is None:
            raise ZoneParseError("'@' used before $ORIGIN", filename, lineno)
        return origin
    if name.endswith('.'):
        return normalize_name(name)
    if origin is None:
        raise ZoneParseError('relative name %r before $ORIGIN' % name,
                             filename, lineno)
    return normalize_name(name + '.' + origin)


def parse_zone(text, filename='<string>', origin=None, default_ttl=300):
    """解析 zone 文件文本，返回 (origin, [Record, ...])。

    origin 为 None 时以文件内第一个 $ORIGIN 为准（否则必须由参数给出）。
    """
    records = []
    current_name = None
    ttl = default_ttl
    for lineno, leading_ws, line in _logical_lines(text, filename):
        tokens = _split_tokens(line)
        if not tokens:
            continue
        head = tokens[0].upper()
        if head.startswith('$'):
            if head == '$ORIGIN':
                if len(tokens) != 2:
                    raise ZoneParseError('$ORIGIN takes exactly one argument',
                                         filename, lineno)
                origin = absolute(tokens[1], origin, filename, lineno)
            elif head == '$TTL':
                if len(tokens) != 2 or not tokens[1].isdigit():
                    raise ZoneParseError('$TTL takes one numeric argument',
                                         filename, lineno)
                ttl = int(tokens[1])
            else:
                raise ZoneParseError('unknown directive %s' % tokens[0],
                                     filename, lineno)
            continue

        idx = 0
        if leading_ws:
            if current_name is None:
                raise ZoneParseError('record without owner name',
                                     filename, lineno)
            name = current_name
        else:
            name = tokens[0]
            idx = 1
            current_name = name

        rec_ttl = ttl
        rclass = CLASS_IN
        # type 之前可以按任意顺序出现 TTL 和 CLASS
        while idx < len(tokens):
            tok = tokens[idx].upper()
            if tok in TYPES:
                break
            if tok.isdigit():
                rec_ttl = int(tokens[idx])
            elif tok in _CLASSES:
                if tok != 'IN':
                    raise ZoneParseError('only class IN is supported',
                                         filename, lineno)
            else:
                raise ZoneParseError('expected TTL/class/type, got %r'
                                     % tokens[idx], filename, lineno)
            idx += 1
        if idx >= len(tokens):
            raise ZoneParseError('missing record type', filename, lineno)
        rtype = TYPES[tokens[idx].upper()]
        rdata_tokens = tokens[idx + 1:]
        if not rdata_tokens:
            raise ZoneParseError('missing rdata', filename, lineno)

        owner = absolute(name, origin, filename, lineno)
        rdata = _parse_rdata_tokens(rtype, rdata_tokens, origin, filename, lineno)
        records.append(Record(owner, rtype, rclass, rec_ttl, rdata))
    if origin is None:
        raise ZoneParseError('no $ORIGIN defined', filename, 0)
    return origin, records


def _parse_rdata_tokens(rtype, tokens, origin, filename, lineno):
    def err(msg):
        raise ZoneParseError(msg, filename, lineno)

    if rtype == TYPE_A:
        if len(tokens) != 1:
            err('A record takes exactly one IPv4 address')
        parts = tokens[0].split('.')
        if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255
                                      for p in parts):
            err('invalid IPv4 address %r' % tokens[0])
        return tokens[0]
    if rtype == TYPE_AAAA:
        if len(tokens) != 1 or ':' not in tokens[0]:
            err('AAAA record takes exactly one IPv6 address')
        import socket
        try:
            socket.inet_pton(socket.AF_INET6, tokens[0])
        except OSError:
            err('invalid IPv6 address %r' % tokens[0])
        return tokens[0]
    if rtype in (TYPE_CNAME, TYPE_NS):
        if len(tokens) != 1:
            err('%s record takes exactly one name' %
                ('CNAME' if rtype == TYPE_CNAME else 'NS'))
        return absolute(tokens[0], origin, filename, lineno)
    if rtype == TYPE_MX:
        if len(tokens) != 2 or not tokens[0].isdigit():
            err('MX record takes <priority> <name>')
        return (int(tokens[0]), absolute(tokens[1], origin, filename, lineno))
    if rtype == TYPE_TXT:
        return list(tokens)
    if rtype == TYPE_SOA:
        if len(tokens) != 7:
            err('SOA record takes <mname> <rname> + 5 numbers')
        nums = tokens[2:]
        if not all(n.isdigit() for n in nums):
            err('SOA serial/refresh/retry/expire/minimum must be numbers')
        return (absolute(tokens[0], origin, filename, lineno),
                absolute(tokens[1], origin, filename, lineno),
                int(nums[0]), int(nums[1]), int(nums[2]),
                int(nums[3]), int(nums[4]))
    err('unsupported record type in zone file')


class Zone(object):
    """一个权威区域：按 (名字, 类型) 存记录，查询时轮询。"""

    def __init__(self, origin):
        self.origin = normalize_name(origin)
        self._records = {}   # (name, rtype) -> [Record]
        self._names = set()  # 区域内出现过的所有 owner 名
        self._rr_pos = {}    # (name, rtype) -> 轮询起始位置
        self._lock = threading.Lock()

    def add(self, record):
        key = (record.name, record.type)
        with self._lock:
            self._records.setdefault(key, []).append(record)
            self._names.add(record.name)

    def has_name(self, name):
        return normalize_name(name) in self._names

    def get(self, name, rtype):
        """取 (name, rtype) 的记录，多条时每次轮换起始位置（round-robin）。"""
        key = (normalize_name(name), rtype)
        with self._lock:
            recs = self._records.get(key)
            if not recs:
                return []
            if len(recs) == 1:
                return list(recs)
            pos = self._rr_pos.get(key, 0)
            self._rr_pos[key] = (pos + 1) % len(recs)
            return recs[pos:] + recs[:pos]


class ZoneStore(object):
    """多个 zone 的集合，按最长后缀匹配查找所属区域。"""

    def __init__(self):
        self.zones = {}  # origin -> Zone

    def add_zone(self, zone):
        self.zones[zone.origin] = zone

    def load_file(self, path):
        with open(path, 'r') as f:
            text = f.read()
        origin, records = parse_zone(text, filename=path)
        zone = self.zones.get(origin)
        if zone is None:
            zone = Zone(origin)
            self.zones[origin] = zone
        for rec in records:
            zone.add(rec)
        return zone

    def load_dir(self, path):
        loaded = []
        for fname in sorted(os.listdir(path)):
            fpath = os.path.join(path, fname)
            if os.path.isfile(fpath) and not fname.startswith('.'):
                loaded.append(self.load_file(fpath))
        return loaded

    def find_zone(self, name):
        name = normalize_name(name)
        best = None
        for origin, zone in self.zones.items():
            if name == origin or name.endswith('.' + origin):
                if best is None or len(origin) > len(best.origin):
                    best = zone
        return best

    def lookup(self, qname, qtype):
        """权威查询。返回 None 表示不在任何区域内（应走递归）；

        否则返回 (rcode, answers)。跟随 CNAME 链，链断给 NXDOMAIN，
        CNAME 成环给 SERVFAIL。
        """
        zone = self.find_zone(qname)
        if zone is None:
            return None
        qname = normalize_name(qname)
        answers = []
        current = qname
        seen = set()
        while True:
            if current in seen:
                return RCODE_SERVFAIL, answers  # CNAME 环
            seen.add(current)
            recs = zone.get(current, qtype)
            if recs:
                answers.extend(recs)
                return RCODE_NOERROR, answers
            if qtype != TYPE_CNAME:
                cnames = zone.get(current, TYPE_CNAME)
                if cnames:
                    answers.extend(cnames)
                    current = cnames[0].rdata
                    continue
            if zone.has_name(current):
                return RCODE_NOERROR, answers  # NODATA：名字存在但没这个类型
            # 名字不存在（或 CNAME 链断在区域外）
            return RCODE_NXDOMAIN, answers
