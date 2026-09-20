"""DNS 报文编解码（RFC 1035），纯标准库实现。

每个字节都自己拼、自己解：Header / Question / Resource Record /
域名标签编码 / 消息压缩（0xC0 指针，含指针环检测）。
"""

import socket
import struct

# ---------------------------------------------------------------- 常量

# RCODE
RCODE_NOERROR = 0
RCODE_FORMERR = 1
RCODE_SERVFAIL = 2
RCODE_NXDOMAIN = 3
RCODE_NOTIMP = 4
RCODE_REFUSED = 5

RCODE_NAMES = {
    RCODE_NOERROR: "NOERROR",
    RCODE_FORMERR: "FORMERR",
    RCODE_SERVFAIL: "SERVFAIL",
    RCODE_NXDOMAIN: "NXDOMAIN",
    RCODE_NOTIMP: "NOTIMP",
    RCODE_REFUSED: "REFUSED",
}

# QCLASS
CLASS_IN = 1

# QTYPE
TYPE_A = 1
TYPE_NS = 2
TYPE_CNAME = 5
TYPE_SOA = 6
TYPE_MX = 15
TYPE_TXT = 16
TYPE_AAAA = 28

TYPE_BY_NAME = {
    "A": TYPE_A,
    "NS": TYPE_NS,
    "CNAME": TYPE_CNAME,
    "SOA": TYPE_SOA,
    "MX": TYPE_MX,
    "TXT": TYPE_TXT,
    "AAAA": TYPE_AAAA,
}
NAME_BY_TYPE = {v: k for k, v in TYPE_BY_NAME.items()}

OPCODE_QUERY = 0

MAX_LABEL_LEN = 63
MAX_NAME_LEN = 255
MAX_POINTER = 0x3FFF  # 压缩指针可表示的最大偏移

HEADER_LEN = 12
HEADER_STRUCT = struct.Struct("!HHHHHH")


class DNSError(Exception):
    """报文解析/编码错误。解析端遇到它应回 FORMERR。"""


def type_to_name(rtype):
    return NAME_BY_TYPE.get(rtype, "TYPE%d" % rtype)


def name_to_type(name):
    name = name.upper()
    if name in TYPE_BY_NAME:
        return TYPE_BY_NAME[name]
    if name.startswith("TYPE") and name[4:].isdigit():
        return int(name[4:])
    raise ValueError("unknown type: %r" % name)


def rcode_to_name(rcode):
    return RCODE_NAMES.get(rcode, "RCODE%d" % rcode)


# ---------------------------------------------------------------- 域名编解码

def encode_name(name, buf, compression):
    """把域名按标签编码追加到 buf（bytearray）。

    compression: dict，key 为小写域名后缀，value 为报文内偏移。
    能复用已有后缀时写 0xC0 压缩指针。
    """
    labels = name.split(".") if name else []
    i = 0
    while i < len(labels):
        suffix = ".".join(labels[i:]).lower()
        ptr = compression.get(suffix)
        if ptr is not None:
            buf += struct.pack("!H", 0xC000 | ptr)
            return
        if len(buf) <= MAX_POINTER and suffix not in compression:
            compression[suffix] = len(buf)
        label = labels[i].encode("ascii", "replace")
        if not label or len(label) > MAX_LABEL_LEN:
            raise DNSError("bad label length: %r" % labels[i])
        buf.append(len(label))
        buf += label
        i += 1
    buf.append(0)


def decode_name(data, offset):
    """从 data[offset] 解析域名，返回 (name, 下一个字段的偏移)。

    支持压缩指针；检测指针环（A->B->A），发现即抛 DNSError。
    """
    labels = []
    visited = set()
    jumped = False
    pos = offset
    end = None
    total = 0
    while True:
        if pos >= len(data):
            raise DNSError("truncated name at offset %d" % pos)
        length = data[pos]
        if length & 0xC0 == 0xC0:
            # 压缩指针：两字节，高两位 11
            if pos + 1 >= len(data):
                raise DNSError("truncated compression pointer")
            ptr = ((length & 0x3F) << 8) | data[pos + 1]
            if ptr in visited:
                raise DNSError("compression pointer loop detected")
            visited.add(ptr)
            if not jumped:
                end = pos + 2
                jumped = True
            pos = ptr
            continue
        if length & 0xC0:
            raise DNSError("reserved label bits set: 0x%02x" % length)
        pos += 1
        if length == 0:
            if not jumped:
                end = pos
            break
        if pos + length > len(data):
            raise DNSError("truncated label")
        labels.append(data[pos:pos + length].decode("ascii", "replace"))
        total += length + 1
        if total > MAX_NAME_LEN:
            raise DNSError("name too long")
        pos += length
    return ".".join(labels), end


# ---------------------------------------------------------------- RDATA

class RData:
    """RDATA 基类。子类实现 encode/decode。"""

    def encode(self, buf, compression):
        raise NotImplementedError

    def __eq__(self, other):
        return type(self) is type(other) and self.__dict__ == other.__dict__

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        inner = ", ".join("%s=%r" % kv for kv in self.__dict__.items())
        return "%s(%s)" % (type(self).__name__, inner)


class ARecord(RData):
    def __init__(self, address):
        self.address = address

    def encode(self, buf, compression):
        buf += socket.inet_pton(socket.AF_INET, self.address)

    @classmethod
    def decode(cls, data, offset, length):
        if length != 4:
            raise DNSError("bad A rdata length %d" % length)
        return cls(socket.inet_ntop(socket.AF_INET, data[offset:offset + 4]))

    def __str__(self):
        return self.address


class AAAARecord(RData):
    def __init__(self, address):
        self.address = address

    def encode(self, buf, compression):
        buf += socket.inet_pton(socket.AF_INET6, self.address)

    @classmethod
    def decode(cls, data, offset, length):
        if length != 16:
            raise DNSError("bad AAAA rdata length %d" % length)
        return cls(socket.inet_ntop(socket.AF_INET6, data[offset:offset + 16]))

    def __str__(self):
        return self.address


class _NameRData(RData):
    """RDATA 为单个域名的类型（NS / CNAME）。"""

    def __init__(self, name):
        self.name = name

    def encode(self, buf, compression):
        encode_name(self.name, buf, compression)

    @classmethod
    def decode(cls, data, offset, length):
        name, _ = decode_name(data, offset)
        return cls(name)

    def __str__(self):
        return self.name + "."


class NSRecord(_NameRData):
    pass


class CNAMERecord(_NameRData):
    pass


class MXRecord(RData):
    def __init__(self, preference, exchange):
        self.preference = preference
        self.exchange = exchange

    def encode(self, buf, compression):
        buf += struct.pack("!H", self.preference)
        encode_name(self.exchange, buf, compression)

    @classmethod
    def decode(cls, data, offset, length):
        if length < 3:
            raise DNSError("bad MX rdata length %d" % length)
        (preference,) = struct.unpack_from("!H", data, offset)
        exchange, _ = decode_name(data, offset + 2)
        return cls(preference, exchange)

    def __str__(self):
        return "%d %s." % (self.preference, self.exchange)


class TXTRecord(RData):
    def __init__(self, strings):
        if isinstance(strings, (str, bytes)):
            strings = [strings]
        self.strings = list(strings)

    def encode(self, buf, compression):
        for s in self.strings:
            raw = s.encode("utf-8") if isinstance(s, str) else bytes(s)
            # 单个 character-string 最长 255，超长自动分片
            for i in range(0, max(len(raw), 1), 255):
                chunk = raw[i:i + 255]
                buf.append(len(chunk))
                buf += chunk

    @classmethod
    def decode(cls, data, offset, length):
        strings = []
        pos = offset
        end = offset + length
        while pos < end:
            slen = data[pos]
            pos += 1
            if pos + slen > end:
                raise DNSError("truncated TXT character-string")
            strings.append(data[pos:pos + slen].decode("utf-8", "replace"))
            pos += slen
        if not strings:
            raise DNSError("empty TXT rdata")
        return cls(strings)

    def __str__(self):
        return " ".join('"%s"' % s for s in self.strings)


class SOARecord(RData):
    def __init__(self, mname, rname, serial, refresh, retry, expire, minimum):
        self.mname = mname
        self.rname = rname
        self.serial = serial
        self.refresh = refresh
        self.retry = retry
        self.expire = expire
        self.minimum = minimum

    def encode(self, buf, compression):
        encode_name(self.mname, buf, compression)
        encode_name(self.rname, buf, compression)
        buf += struct.pack("!IIIII", self.serial, self.refresh,
                           self.retry, self.expire, self.minimum)

    @classmethod
    def decode(cls, data, offset, length):
        mname, pos = decode_name(data, offset)
        rname, pos = decode_name(data, pos)
        if pos + 20 > offset + length:
            raise DNSError("truncated SOA rdata")
        serial, refresh, retry, expire, minimum = struct.unpack_from("!IIIII", data, pos)
        return cls(mname, rname, serial, refresh, retry, expire, minimum)

    def __str__(self):
        return "%s. %s. %d %d %d %d %d" % (
            self.mname, self.rname, self.serial,
            self.refresh, self.retry, self.expire, self.minimum)


class UnknownRData(RData):
    """不认识的记录类型：RDATA 原样保留，绝不尝试解压其中的字节。"""

    def __init__(self, data):
        self.data = bytes(data)

    def encode(self, buf, compression):
        buf += self.data

    @classmethod
    def decode(cls, data, offset, length):
        return cls(data[offset:offset + length])

    def __str__(self):
        return "\\# %d %s" % (len(self.data), self.data.hex())


RDATA_BY_TYPE = {
    TYPE_A: ARecord,
    TYPE_AAAA: AAAARecord,
    TYPE_NS: NSRecord,
    TYPE_CNAME: CNAMERecord,
    TYPE_MX: MXRecord,
    TYPE_TXT: TXTRecord,
    TYPE_SOA: SOARecord,
}


def rdata_class(rtype):
    return RDATA_BY_TYPE.get(rtype, UnknownRData)


# ---------------------------------------------------------------- 报文结构

class Question:
    def __init__(self, qname, qtype, qclass=CLASS_IN):
        self.qname = qname
        self.qtype = qtype
        self.qclass = qclass

    def __eq__(self, other):
        return (isinstance(other, Question)
                and self.qname.lower() == other.qname.lower()
                and self.qtype == other.qtype
                and self.qclass == other.qclass)

    def __repr__(self):
        return "Question(%r, %s, %d)" % (
            self.qname, type_to_name(self.qtype), self.qclass)


class ResourceRecord:
    def __init__(self, name, rtype, rclass, ttl, rdata):
        self.name = name
        self.rtype = rtype
        self.rclass = rclass
        self.ttl = ttl
        self.rdata = rdata

    def copy_with_ttl(self, ttl):
        return ResourceRecord(self.name, self.rtype, self.rclass, ttl, self.rdata)

    def __eq__(self, other):
        return (isinstance(other, ResourceRecord)
                and self.name.lower() == other.name.lower()
                and self.rtype == other.rtype
                and self.rclass == other.rclass
                and self.ttl == other.ttl
                and self.rdata == other.rdata)

    def __repr__(self):
        return "RR(%s %d %s %r)" % (
            self.name, self.ttl, type_to_name(self.rtype), self.rdata)

    def __str__(self):
        return "%s. %d IN %s %s" % (
            self.name, self.ttl, type_to_name(self.rtype), self.rdata)


class Message:
    """一个完整的 DNS 报文。"""

    def __init__(self):
        self.id = 0
        self.qr = 0
        self.opcode = OPCODE_QUERY
        self.aa = 0
        self.tc = 0
        self.rd = 0
        self.ra = 0
        self.rcode = RCODE_NOERROR
        self.questions = []
        self.answers = []
        self.authorities = []
        self.additionals = []

    # ---- flags ----

    def _encode_flags(self):
        flags = 0
        flags |= (self.qr & 0x1) << 15
        flags |= (self.opcode & 0xF) << 11
        flags |= (self.aa & 0x1) << 10
        flags |= (self.tc & 0x1) << 9
        flags |= (self.rd & 0x1) << 8
        flags |= (self.ra & 0x1) << 7
        flags |= self.rcode & 0xF
        return flags

    def _decode_flags(self, flags):
        self.qr = (flags >> 15) & 0x1
        self.opcode = (flags >> 11) & 0xF
        self.aa = (flags >> 10) & 0x1
        self.tc = (flags >> 9) & 0x1
        self.rd = (flags >> 8) & 0x1
        self.ra = (flags >> 7) & 0x1
        self.rcode = flags & 0xF

    # ---- 编码 ----

    def encode(self):
        buf = bytearray()
        compression = {}
        buf += HEADER_STRUCT.pack(
            self.id, self._encode_flags(),
            len(self.questions), len(self.answers),
            len(self.authorities), len(self.additionals))
        for q in self.questions:
            encode_name(q.qname, buf, compression)
            buf += struct.pack("!HH", q.qtype, q.qclass)
        for section in (self.answers, self.authorities, self.additionals):
            for rr in section:
                _encode_rr(rr, buf, compression)
        return bytes(buf)

    # ---- 解码 ----

    @classmethod
    def decode(cls, data):
        if len(data) < HEADER_LEN:
            raise DNSError("message too short: %d bytes" % len(data))
        (msg_id, flags, qdcount, ancount,
         nscount, arcount) = HEADER_STRUCT.unpack_from(data, 0)
        msg = cls()
        msg.id = msg_id
        msg._decode_flags(flags)
        offset = HEADER_LEN
        for _ in range(qdcount):
            qname, offset = decode_name(data, offset)
            if offset + 4 > len(data):
                raise DNSError("truncated question")
            qtype, qclass = struct.unpack_from("!HH", data, offset)
            offset += 4
            msg.questions.append(Question(qname, qtype, qclass))
        for section, count in ((msg.answers, ancount),
                               (msg.authorities, nscount),
                               (msg.additionals, arcount)):
            for _ in range(count):
                rr, offset = _decode_rr(data, offset)
                section.append(rr)
        return msg

    def make_response(self, rcode=RCODE_NOERROR):
        """以本查询为模板构造应答报文（同 ID、回显 Question）。"""
        resp = Message()
        resp.id = self.id
        resp.qr = 1
        resp.opcode = self.opcode
        resp.rd = self.rd
        resp.rcode = rcode
        resp.questions = list(self.questions)
        return resp

    def __repr__(self):
        return ("Message(id=%d qr=%d rcode=%s qd=%d an=%d ns=%d ar=%d)"
                % (self.id, self.qr, rcode_to_name(self.rcode),
                   len(self.questions), len(self.answers),
                   len(self.authorities), len(self.additionals)))


def _encode_rr(rr, buf, compression):
    encode_name(rr.name, buf, compression)
    buf += struct.pack("!HHI", rr.rtype, rr.rclass, rr.ttl)
    rdlen_pos = len(buf)
    buf += b"\x00\x00"  # RDLENGTH 占位，写完 RDATA 回填
    start = len(buf)
    rr.rdata.encode(buf, compression)
    rdlen = len(buf) - start
    if rdlen > 0xFFFF:
        raise DNSError("rdata too long")
    buf[rdlen_pos:rdlen_pos + 2] = struct.pack("!H", rdlen)


def _decode_rr(data, offset):
    name, offset = decode_name(data, offset)
    if offset + 10 > len(data):
        raise DNSError("truncated resource record header")
    rtype, rclass, ttl, rdlength = struct.unpack_from("!HHIH", data, offset)
    offset += 10
    if offset + rdlength > len(data):
        raise DNSError("truncated rdata")
    cls = rdata_class(rtype)
    rdata = cls.decode(data, offset, rdlength)
    return ResourceRecord(name, rtype, rclass, ttl, rdata), offset + rdlength
