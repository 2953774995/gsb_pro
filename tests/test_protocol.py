"""报文编解码：roundtrip、flags、压缩指针、畸形报文。"""

import struct

import pytest

from minidns import protocol as P


def make_query(qid=0x1234, name="example.com", qtype=P.TYPE_A, rd=1):
    msg = P.Message()
    msg.id = qid
    msg.rd = rd
    msg.questions.append(P.Question(name, qtype, P.CLASS_IN))
    return msg


# ---------------------------------------------------------------- roundtrip

def test_standard_query_roundtrip_byte_exact():
    # 手工构造的标准查询报文：example.com A IN
    raw = bytes.fromhex(
        "1234"      # ID
        "0100"      # flags: RD
        "0001"      # QDCOUNT
        "0000"      # ANCOUNT
        "0000"      # NSCOUNT
        "0000"      # ARCOUNT
        "076578616d706c6503636f6d00"  # example.com
        "0001"      # QTYPE=A
        "0001"      # QCLASS=IN
    )
    msg = P.Message.decode(raw)
    assert msg.id == 0x1234
    assert msg.rd == 1 and msg.qr == 0
    assert len(msg.questions) == 1
    q = msg.questions[0]
    assert q.qname == "example.com"
    assert q.qtype == P.TYPE_A
    assert q.qclass == P.CLASS_IN
    # 解析后再编码，字节级一致
    assert msg.encode() == raw


def test_response_roundtrip_byte_exact():
    query = make_query()
    resp = query.make_response()
    resp.ra = 1
    resp.answers.append(P.ResourceRecord(
        "example.com", P.TYPE_A, P.CLASS_IN, 300, P.ARecord("93.184.216.34")))
    raw = resp.encode()
    again = P.Message.decode(raw)
    assert again.encode() == raw
    assert again.answers[0].rdata.address == "93.184.216.34"
    assert again.answers[0].ttl == 300


def test_flags_bit_operations():
    msg = P.Message()
    msg.qr = 1
    msg.opcode = 2
    msg.aa = 1
    msg.tc = 1
    msg.rd = 1
    msg.ra = 1
    msg.rcode = P.RCODE_NXDOMAIN
    raw = msg.encode()
    (flags,) = struct.unpack_from("!H", raw, 2)
    assert flags & 0x8000  # QR
    assert (flags >> 11) & 0xF == 2  # Opcode
    assert flags & 0x0400  # AA
    assert flags & 0x0200  # TC
    assert flags & 0x0100  # RD
    assert flags & 0x0080  # RA
    assert flags & 0x000F == 3  # RCODE
    back = P.Message.decode(raw)
    assert (back.qr, back.opcode, back.aa, back.tc, back.rd, back.ra,
            back.rcode) == (1, 2, 1, 1, 1, 1, 3)


def test_all_rcodes_roundtrip():
    for rcode in (P.RCODE_NOERROR, P.RCODE_FORMERR, P.RCODE_SERVFAIL,
                  P.RCODE_NXDOMAIN, P.RCODE_NOTIMP):
        msg = make_query().make_response(rcode)
        assert P.Message.decode(msg.encode()).rcode == rcode


# ---------------------------------------------------------------- 压缩指针

def test_compression_reuses_question_name():
    query = make_query(name="www.example.com")
    resp = query.make_response()
    resp.answers.append(P.ResourceRecord(
        "www.example.com", P.TYPE_A, P.CLASS_IN, 60, P.ARecord("1.2.3.4")))
    raw = resp.encode()
    # 应答里的名字应编码为指向 offset 12 的压缩指针
    assert b"\xc0\x0c" in raw
    decoded = P.Message.decode(raw)
    assert decoded.answers[0].name == "www.example.com"


def test_compression_suffix_reuse():
    # 两个不同名字共享后缀 example.com，后者应部分压缩
    msg = P.Message()
    msg.questions.append(P.Question("a.example.com", P.TYPE_A))
    msg.answers.append(P.ResourceRecord(
        "b.example.com", P.TYPE_A, P.CLASS_IN, 60, P.ARecord("1.2.3.4")))
    raw = msg.encode()
    # "b" 标签后面应跟一个压缩指针（指向 example.com）
    assert b"\x01b\xc0" in raw
    decoded = P.Message.decode(raw)
    assert decoded.answers[0].name == "b.example.com"


def test_decode_pointer_loop_ab_ba():
    # offset 12: 指针 -> 14；offset 14: 指针 -> 12（A 指 B、B 指 A）
    raw = b"\x00" * 12 + b"\xc0\x0e" + b"\xc0\x0c"
    with pytest.raises(P.DNSError):
        P.decode_name(raw, 12)


def test_decode_pointer_self_loop():
    raw = b"\x00" * 12 + b"\xc0\x0c"  # 指向自己
    with pytest.raises(P.DNSError):
        P.decode_name(raw, 12)


def test_decode_pointer_out_of_bounds():
    raw = b"\x00" * 12 + b"\xc0\xff"
    with pytest.raises(P.DNSError):
        P.decode_name(raw, 12)


def test_decode_truncated_message():
    with pytest.raises(P.DNSError):
        P.Message.decode(b"\x12\x34\x01")  # 不足 12 字节
    raw = make_query().encode()
    with pytest.raises(P.DNSError):
        P.Message.decode(raw[:-2])  # 截掉 QCLASS


def test_decode_qdcount_lies():
    # QDCOUNT=2 但报文里只有 1 个问题
    raw = bytearray(make_query().encode())
    raw[4:6] = struct.pack("!H", 2)
    with pytest.raises(P.DNSError):
        P.Message.decode(bytes(raw))


# ---------------------------------------------------------------- RDATA 类型

@pytest.mark.parametrize("rdata", [
    P.ARecord("192.0.2.1"),
    P.AAAARecord("2001:db8::1"),
    P.NSRecord("ns1.example.com"),
    P.CNAMERecord("target.example.com"),
    P.MXRecord(10, "mail.example.com"),
    P.TXTRecord(["hello world", "v=spf1 -all"]),
    P.TXTRecord("x" * 300),  # 超长自动分片
    P.SOARecord("ns1.example.com", "admin.example.com", 1, 7200, 3600, 1209600, 300),
])
def test_rdata_roundtrip(rdata):
    rtype = {P.ARecord: P.TYPE_A, P.AAAARecord: P.TYPE_AAAA,
             P.NSRecord: P.TYPE_NS, P.CNAMERecord: P.TYPE_CNAME,
             P.MXRecord: P.TYPE_MX, P.TXTRecord: P.TYPE_TXT,
             P.SOARecord: P.TYPE_SOA}[type(rdata)]
    msg = make_query()
    resp = msg.make_response()
    resp.answers.append(P.ResourceRecord("example.com", rtype, P.CLASS_IN, 60, rdata))
    decoded = P.Message.decode(resp.encode())
    got = decoded.answers[0].rdata
    if isinstance(rdata, P.TXTRecord) and len(rdata.strings) == 1 and len(rdata.strings[0]) > 255:
        assert "".join(got.strings) == rdata.strings[0]
    else:
        assert got == rdata


def test_unknown_type_raw_passthrough():
    # TYPE65 (HTTPS)：不认识的类型，RDATA 原样保留
    raw_rdata = bytes.fromhex("0001000001000c")
    msg = make_query(qtype=65)
    resp = msg.make_response()
    resp.answers.append(P.ResourceRecord(
        "example.com", 65, P.CLASS_IN, 60, P.UnknownRData(raw_rdata)))
    raw = resp.encode()
    decoded = P.Message.decode(raw)
    assert decoded.answers[0].rtype == 65
    assert isinstance(decoded.answers[0].rdata, P.UnknownRData)
    assert decoded.answers[0].rdata.data == raw_rdata
    assert decoded.encode() == raw


def test_name_case_insensitive_comparison():
    q1 = P.Question("WWW.Example.COM", P.TYPE_A)
    q2 = P.Question("www.example.com", P.TYPE_A)
    assert q1 == q2
