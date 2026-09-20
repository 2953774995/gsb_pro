"""DNS 报文编解码（RFC 1035）：Header / Question / ResourceRecord / 名字压缩。

只使用标准库。模块内部所有域名一律规范化为小写、以 '.' 结尾的绝对名。
"""

import socket
import struct

CLASS_IN = 1

RCODE_NOERROR = 0
RCODE_FORMERR = 1
RCODE_SERVFAIL = 2
RCODE_NXDOMAIN = 3
RCODE_NOTIMP = 4

RCODE_NAMES = {
    0: 'NOERROR', 1: 'FORMERR', 2: 'SERVFAIL', 3: 'NXDOMAIN',
    4: 'NOTIMP', 5: 'REFUSED',
}

TYPE_A = 1
TYPE_NS = 2
TYPE_CNAME = 5
TYPE_SOA = 6
TYPE_PTR = 12
TYPE_MX = 15
TYPE_TXT = 16
TYPE_AAAA = 28

TYPES = {
    'A': TYPE_A, 'NS': TYPE_NS, 'CNAME': TYPE_CNAME, 'SOA': TYPE_SOA,
    'PTR': TYPE_PTR, 'MX': TYPE_MX, 'TXT': TYPE_TXT, 'AAAA': TYPE_AAAA,
}
TYPE_NAMES = {v: k for k, v in TYPES.items()}

# 名字里包含域名字段、因此 RDATA 可以参与压缩的类型
_NAME_RDATA_TYPES = (TYPE_CNAME, TYPE_NS, TYPE_PTR)

_MAX_POINTER_FOLLOWS = 128  # 防御压缩指针环/异常报文的硬上限


class DNSFormatError(Exception):
    """报文格式错误，对应 RCODE=FORMERR。"""


def type_to_str(rtype):
    return TYPE_NAMES.get(rtype, 'TYPE%d' % rtype)


def type_from_str(s):
    s = s.upper()
    if s in TYPES:
        return TYPES[s]
    if s.startswith('TYPE') and s[4:].isdigit():
        return int(s[4:])
    raise ValueError('unknown record type: %s' % s)


def rcode_to_str(rcode):
    return RCODE_NAMES.get(rcode, 'RCODE%d' % rcode)


def normalize_name(name):
    """规范化为小写、以点结尾的绝对域名。根域为 '.'。"""
    name = name.strip()
    if name in ('', '.'):
        return '.'
    if not name.endswith('.'):
        name += '.'
    return name.lower()


# ---------------------------------------------------------------------------
# 域名编解码（含 message compression）
# ---------------------------------------------------------------------------

def decode_name(data, offset):
    """从 data[offset] 解码一个（可能被压缩的）域名。

    返回 (name, next_offset)。next_offset 是“逻辑上”该名字结束之后的位置
    （遇到压缩指针时，是指针本身之后的位置，而不是指针指向的位置）。
    指针环会抛出 DNSFormatError。
    """
    labels = []
    visited = set()
    jumped = False
    next_offset = None
    cur = offset
    follows = 0
    while True:
        if cur >= len(data):
            raise DNSFormatError('name runs past end of message')
        length = data[cur]
        if length & 0xC0 == 0xC0:
            # 压缩指针：两字节，前两位 11
            if cur + 1 >= len(data):
                raise DNSFormatError('truncated compression pointer')
            ptr = ((length & 0x3F) << 8) | data[cur + 1]
            if ptr in visited:
                raise DNSFormatError('compression pointer loop')
            visited.add(ptr)
            follows += 1
            if follows > _MAX_POINTER_FOLLOWS:
                raise DNSFormatError('too many compression pointers')
            if not jumped:
                next_offset = cur + 2
                jumped = True
            cur = ptr
            continue
        if length & 0xC0:
            raise DNSFormatError('unknown label type 0x%02x' % length)
        if length == 0:
            if not jumped:
                next_offset = cur + 1
            break
        cur += 1
        if cur + length > len(data):
            raise DNSFormatError('label runs past end of message')
        # latin-1 保证字节级无损还原（任意字节 <-> 字符一一对应）
        labels.append(data[cur:cur + length].decode('latin-1'))
        cur += length
    name = '.'.join(labels) + '.' if labels else '.'
    return name, next_offset


def encode_name(name, buf, compression):
    """把域名编码进 bytearray buf。

    compression 是 {小写绝对后缀名: 偏移} 的字典，用于生成压缩指针；
    调用方在同一条报文内共享它。返回 buf。
    """
    name = normalize_name(name)
    if name == '.':
        buf += b'\x00'
        return buf
    labels = name[:-1].split('.')
    i = 0
    while i < len(labels):
        suffix = '.'.join(labels[i:]) + '.'
        ptr = compression.get(suffix)
        if ptr is not None:
            buf += struct.pack('!H', 0xC000 | ptr)
            return buf
        # 只有偏移 < 0x4000 的名字才能被将来的指针引用
        if len(buf) < 0x4000:
            compression[suffix] = len(buf)
        raw = labels[i].encode('latin-1')
        if len(raw) > 63:
            raise DNSFormatError('label too long: %r' % labels[i])
        buf += bytes([len(raw)]) + raw
        i += 1
    buf += b'\x00'
    return buf


# ---------------------------------------------------------------------------
# Header / Question / Record / Message
# ---------------------------------------------------------------------------

class Header(object):
    __slots__ = ('id', 'qr', 'opcode', 'aa', 'tc', 'rd', 'ra', 'z', 'rcode')

    def __init__(self, id=0, qr=0, opcode=0, aa=0, tc=0, rd=0, ra=0, z=0, rcode=0):
        self.id = id
        self.qr = qr
        self.opcode = opcode
        self.aa = aa
        self.tc = tc
        self.rd = rd
        self.ra = ra
        self.z = z
        self.rcode = rcode

    def pack_flags(self):
        return ((self.qr & 1) << 15 | (self.opcode & 0xF) << 11 |
                (self.aa & 1) << 10 | (self.tc & 1) << 9 |
                (self.rd & 1) << 8 | (self.ra & 1) << 7 |
                (self.z & 0x7) << 4 | (self.rcode & 0xF))

    @classmethod
    def unpack_flags(cls, flags):
        return cls(
            qr=(flags >> 15) & 1,
            opcode=(flags >> 11) & 0xF,
            aa=(flags >> 10) & 1,
            tc=(flags >> 9) & 1,
            rd=(flags >> 8) & 1,
            ra=(flags >> 7) & 1,
            z=(flags >> 4) & 0x7,
            rcode=flags & 0xF,
        )

    def __repr__(self):
        return ('Header(id=%d qr=%d opcode=%d aa=%d tc=%d rd=%d ra=%d rcode=%s)'
                % (self.id, self.qr, self.opcode, self.aa, self.tc, self.rd,
                   self.ra, rcode_to_str(self.rcode)))


class Question(object):
    __slots__ = ('qname', 'qtype', 'qclass')

    def __init__(self, qname, qtype=TYPE_A, qclass=CLASS_IN):
        self.qname = normalize_name(qname)
        self.qtype = qtype
        self.qclass = qclass

    def __repr__(self):
        return 'Question(%s %s %s)' % (self.qname, type_to_str(self.qtype), self.qclass)


class Record(object):
    """资源记录。rdata 按类型存结构化值：

    A -> '1.2.3.4'；AAAA -> '::1'；CNAME/NS/PTR -> 域名字符串；
    MX -> (priority, 域名)；TXT -> [字符串, ...]；
    SOA -> (mname, rname, serial, refresh, retry, expire, minimum)；
    其他未知类型 -> 原始 bytes。
    """
    __slots__ = ('name', 'type', 'rclass', 'ttl', 'rdata')

    def __init__(self, name, rtype, rclass, ttl, rdata):
        self.name = normalize_name(name)
        self.type = rtype
        self.rclass = rclass
        self.ttl = int(ttl)
        self.rdata = rdata

    def copy_with_ttl(self, ttl):
        return Record(self.name, self.type, self.rclass, ttl, self.rdata)

    def rdata_to_text(self):
        rd = self.rdata
        if self.type == TYPE_MX:
            return '%d %s' % (rd[0], rd[1])
        if self.type == TYPE_TXT:
            return ' '.join('"%s"' % s for s in rd)
        if self.type == TYPE_SOA:
            return '%s %s %d %d %d %d %d' % rd
        if isinstance(rd, bytes):
            return '\\# %d %s' % (len(rd), rd.hex())
        return str(rd)

    def __eq__(self, other):
        return (isinstance(other, Record) and self.name == other.name and
                self.type == other.type and self.rclass == other.rclass and
                self.ttl == other.ttl and self.rdata == other.rdata)

    def __repr__(self):
        return 'Record(%s %d %s %s)' % (
            self.name, self.ttl, type_to_str(self.type), self.rdata_to_text())


def _parse_rdata(rtype, data, offset, rdlength):
    end = offset + rdlength
    if end > len(data):
        raise DNSFormatError('rdata runs past end of message')
    if rtype == TYPE_A:
        if rdlength != 4:
            raise DNSFormatError('bad A rdata length')
        return socket.inet_ntoa(data[offset:end])
    if rtype == TYPE_AAAA:
        if rdlength != 16:
            raise DNSFormatError('bad AAAA rdata length')
        return socket.inet_ntop(socket.AF_INET6, data[offset:end])
    if rtype in _NAME_RDATA_TYPES:
        name, _ = decode_name(data, offset)
        return name
    if rtype == TYPE_MX:
        if rdlength < 3:
            raise DNSFormatError('bad MX rdata length')
        (pref,) = struct.unpack('!H', data[offset:offset + 2])
        exchange, _ = decode_name(data, offset + 2)
        return (pref, exchange)
    if rtype == TYPE_TXT:
        txts = []
        cur = offset
        while cur < end:
            ln = data[cur]
            cur += 1
            if cur + ln > end:
                raise DNSFormatError('bad TXT rdata')
            txts.append(data[cur:cur + ln].decode('latin-1'))
            cur += ln
        return txts
    if rtype == TYPE_SOA:
        mname, cur = decode_name(data, offset)
        rname, cur = decode_name(data, cur)
        if cur + 20 > end:
            raise DNSFormatError('bad SOA rdata')
        vals = struct.unpack('!IIIII', data[cur:cur + 20])
        return (mname, rname) + vals
    # 未知类型：保留原始字节，保证能原样转发
    return bytes(data[offset:end])


def _parse_record(data, offset):
    name, offset = decode_name(data, offset)
    if offset + 10 > len(data):
        raise DNSFormatError('truncated resource record')
    rtype, rclass, ttl, rdlength = struct.unpack('!HHIH', data[offset:offset + 10])
    offset += 10
    rdata = _parse_rdata(rtype, data, offset, rdlength)
    offset += rdlength
    return Record(name, rtype, rclass, ttl, rdata), offset


def _encode_rdata(rec, buf, compression):
    rd = rec.rdata
    if rec.type == TYPE_A:
        buf += socket.inet_aton(rd)
    elif rec.type == TYPE_AAAA:
        buf += socket.inet_pton(socket.AF_INET6, rd)
    elif rec.type in _NAME_RDATA_TYPES:
        encode_name(rd, buf, compression)
    elif rec.type == TYPE_MX:
        buf += struct.pack('!H', rd[0])
        encode_name(rd[1], buf, compression)
    elif rec.type == TYPE_TXT:
        for s in rd:
            raw = s.encode('latin-1')
            if len(raw) > 255:
                raise DNSFormatError('TXT string too long')
            buf += bytes([len(raw)]) + raw
    elif rec.type == TYPE_SOA:
        encode_name(rd[0], buf, compression)
        encode_name(rd[1], buf, compression)
        buf += struct.pack('!IIIII', *rd[2:])
    elif isinstance(rd, bytes):
        buf += rd
    else:
        raise DNSFormatError('cannot encode rdata for type %s' % type_to_str(rec.type))


def _encode_record(rec, buf, compression):
    encode_name(rec.name, buf, compression)
    buf += struct.pack('!HHI', rec.type, rec.rclass, max(0, rec.ttl))
    len_pos = len(buf)
    buf += b'\x00\x00'  # RDLENGTH 占位，编码完回填
    start = len(buf)
    _encode_rdata(rec, buf, compression)
    struct.pack_into('!H', buf, len_pos, len(buf) - start)


class Message(object):
    def __init__(self, header=None):
        self.header = header or Header()
        self.questions = []
        self.answers = []
        self.authorities = []
        self.additionals = []

    @classmethod
    def parse(cls, data):
        if len(data) < 12:
            raise DNSFormatError('message shorter than header')
        mid, flags, qd, an, ns, ar = struct.unpack('!HHHHHH', data[:12])
        header = Header.unpack_flags(flags)
        header.id = mid
        msg = cls(header)
        offset = 12
        for _ in range(qd):
            qname, offset = decode_name(data, offset)
            if offset + 4 > len(data):
                raise DNSFormatError('truncated question section')
            qtype, qclass = struct.unpack('!HH', data[offset:offset + 4])
            offset += 4
            msg.questions.append(Question(qname, qtype, qclass))
        for section, count in ((msg.answers, an), (msg.authorities, ns),
                               (msg.additionals, ar)):
            for _ in range(count):
                rec, offset = _parse_record(data, offset)
                section.append(rec)
        return msg

    def to_bytes(self):
        buf = bytearray()
        compression = {}
        buf += struct.pack('!HHHHHH',
                           self.header.id, self.header.pack_flags(),
                           len(self.questions), len(self.answers),
                           len(self.authorities), len(self.additionals))
        for q in self.questions:
            encode_name(q.qname, buf, compression)
            buf += struct.pack('!HH', q.qtype, q.qclass)
        for rec in self.answers + self.authorities + self.additionals:
            _encode_record(rec, buf, compression)
        return bytes(buf)

    def __repr__(self):
        return 'Message(%r q=%d an=%d ns=%d ar=%d)' % (
            self.header, len(self.questions), len(self.answers),
            len(self.authorities), len(self.additionals))


def make_query(qname, qtype, qid=None, rd=True):
    """构造一个标准查询报文。"""
    import random
    if qid is None:
        qid = random.randint(0, 0xFFFF)
    msg = Message(Header(id=qid, qr=0, opcode=0, rd=1 if rd else 0))
    msg.questions.append(Question(qname, qtype, CLASS_IN))
    return msg


def make_error_response(query_id, rcode, question=None):
    """构造一个错误应答（FORMERR/SERVFAIL/NOTIMP 等）。"""
    msg = Message(Header(id=query_id, qr=1, rcode=rcode))
    if question is not None:
        msg.questions.append(question)
    return msg
