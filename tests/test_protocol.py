"""报文编解码：roundtrip、压缩指针、指针环检测。"""

import struct

import pytest

from minidns.protocol import (CLASS_IN, DNSFormatError, Header, Message,
                              Question, Record, TYPE_A, TYPE_AAAA, TYPE_CNAME,
                              TYPE_MX, TYPE_TXT, decode_name, encode_name,
                              make_query)


def build_standard_query():
    """手工拼一个标准 A 查询：example.com，与字节级 roundtrip 对照。"""
    qname = b''
    for label in (b'example', b'com'):
        qname += bytes([len(label)]) + label
    qname += b'\x00'
    header = struct.pack('!HHHHHH', 0x1234, 0x0100, 1, 0, 0, 0)  # RD=1
    return header + qname + struct.pack('!HH', TYPE_A, CLASS_IN)


def test_parse_standard_query_bytes():
    data = build_standard_query()
    msg = Message.parse(data)
    assert msg.header.id == 0x1234
    assert msg.header.qr == 0 and msg.header.rd == 1
    assert len(msg.questions) == 1
    q = msg.questions[0]
    assert q.qname == 'example.com.'
    assert q.qtype == TYPE_A and q.qclass == CLASS_IN


def test_query_roundtrip_byte_identical():
    data = build_standard_query()
    msg = Message.parse(data)
    assert msg.to_bytes() == data


def test_response_roundtrip_with_records():
    msg = Message(Header(id=7, qr=1, aa=1, rd=1, ra=1))
    msg.questions.append(Question('www.example.com', TYPE_A))
    msg.answers.append(Record('www.example.com', TYPE_A, CLASS_IN, 300, '1.2.3.4'))
    msg.answers.append(Record('www.example.com', TYPE_AAAA, CLASS_IN, 300, '::1'))
    msg.answers.append(Record('alias.example.com', TYPE_CNAME, CLASS_IN, 60,
                              'www.example.com.'))
    msg.answers.append(Record('example.com', TYPE_MX, CLASS_IN, 60,
                              (10, 'mail.example.com.')))
    msg.answers.append(Record('example.com', TYPE_TXT, CLASS_IN, 60,
                              ['hello', 'world']))
    data = msg.to_bytes()
    back = Message.parse(data)
    assert back.header.id == 7 and back.header.aa == 1
    assert back.questions[0].qname == 'www.example.com.'
    assert back.answers[0].rdata == '1.2.3.4'
    assert back.answers[1].rdata == '::1'
    assert back.answers[2].rdata == 'www.example.com.'
    assert back.answers[3].rdata == (10, 'mail.example.com.')
    assert back.answers[4].rdata == ['hello', 'world']
    # 再编码仍然一致
    assert back.to_bytes() == data


def test_flags_bit_operations():
    h = Header(id=1, qr=1, opcode=0, aa=1, tc=1, rd=1, ra=1, rcode=3)
    flags = h.pack_flags()
    assert flags == 0x8783  # 1000 0111 1000 0011
    h2 = Header.unpack_flags(flags)
    assert (h2.qr, h2.opcode, h2.aa, h2.tc, h2.rd, h2.ra, h2.rcode) == \
        (1, 0, 1, 1, 1, 1, 3)


def test_compression_produces_pointer():
    msg = Message(Header(id=1, qr=1))
    msg.questions.append(Question('www.example.com', TYPE_A))
    msg.answers.append(Record('www.example.com', TYPE_A, CLASS_IN, 300, '1.2.3.4'))
    data = msg.to_bytes()
    # 应答里的名字应被压缩成指向 Question 的指针 0xC00C（偏移 12）
    assert b'\xc0\x0c' in data
    # 未压缩的话会重复出现完整名字
    assert data.count(b'\x03www\x07example\x03com\x00') == 1


def test_decode_name_follows_pointer():
    # 手工构造：offset 12 是 www.example.com，offset 30 是指向它的指针
    name = b'\x03www\x07example\x03com\x00'
    data = b'\x00' * 12 + name + b'\x00' * 5 + b'\xc0\x0c'
    ptr_off = 12 + len(name) + 5
    decoded, next_off = decode_name(data, ptr_off)
    assert decoded == 'www.example.com.'
    assert next_off == ptr_off + 2


def test_compression_pointer_loop_detected():
    # A(12) 指向 B(14)，B(14) 指向 A(12)
    data = b'\x00' * 12 + b'\xc0\x0e\xc0\x0c'
    with pytest.raises(DNSFormatError):
        decode_name(data, 12)


def test_self_pointer_detected():
    data = b'\x00' * 12 + b'\xc0\x0c'  # 指向自己
    with pytest.raises(DNSFormatError):
        decode_name(data, 12)


def test_truncated_message_raises():
    with pytest.raises(DNSFormatError):
        Message.parse(b'\x00' * 5)  # 不足 12 字节头


def test_qdcount_lies_raises():
    # QDCOUNT=2 但报文里只有一个 question
    data = build_standard_query()
    data = data[:4] + struct.pack('!H', 2) + data[6:]
    with pytest.raises(DNSFormatError):
        Message.parse(data)


def test_case_insensitive_names():
    q1 = Question('WWW.Example.COM', TYPE_A)
    q2 = Question('www.example.com.', TYPE_A)
    assert q1.qname == q2.qname == 'www.example.com.'


def test_unknown_type_preserved_as_bytes():
    # TYPE65 (HTTPS) 之类未知类型：rdata 原样保留，不崩
    msg = Message(Header(id=9, qr=1))
    msg.questions.append(Question('example.com', 65))
    msg.answers.append(Record('example.com', 65, CLASS_IN, 60, b'\x00\x01raw'))
    data = msg.to_bytes()
    back = Message.parse(data)
    assert back.answers[0].type == 65
    assert back.answers[0].rdata == b'\x00\x01raw'
    assert back.to_bytes() == data
