"""解码时遇到未知字段编号要按 wire type 跳过，不能崩。"""

from minipb import wire
from minipb.runtime import Field, Message


class Known(Message):
    _fields = [
        Field("name", 1, "string", "optional"),
        Field("age", 2, "int32", "optional"),
    ]


def _unknown(number, wire_type, payload):
    return wire.encode_tag(number, wire_type) + payload


def test_skip_unknown_fields_all_wire_types():
    data = b""
    # 已知字段 1: name = "ab"
    data += wire.encode_tag(1, wire.WIRE_LEN) + b"\x02ab"
    # 未知字段 100, varint
    data += _unknown(100, wire.WIRE_VARINT, wire.encode_varint(12345))
    # 未知字段 101, 64-bit
    data += _unknown(101, wire.WIRE_64BIT, b"\x00" * 8)
    # 未知字段 102, length-delimited
    data += _unknown(102, wire.WIRE_LEN, b"\x03xyz")
    # 未知字段 103, 32-bit
    data += _unknown(103, wire.WIRE_32BIT, b"\xde\xad\xbe\xef")
    # 已知字段 2: age = 30
    data += wire.encode_tag(2, wire.WIRE_VARINT) + wire.encode_varint(30)

    msg = Known.decode(data)
    assert msg.name == "ab"
    assert msg.age == 30


def test_unknown_field_only():
    data = _unknown(7, wire.WIRE_VARINT, wire.encode_varint(1))
    msg = Known.decode(data)
    assert msg.name is None
    assert msg.age is None


def test_unknown_field_roundtrip_stable():
    # 未知字段被丢弃，重新编码后只剩已知字段（这是预期行为）
    data = _unknown(7, wire.WIRE_VARINT, wire.encode_varint(1))
    data += wire.encode_tag(2, wire.WIRE_VARINT) + wire.encode_varint(5)
    msg = Known.decode(data)
    assert msg.encode() == wire.encode_tag(2, wire.WIRE_VARINT) + b"\x05"
