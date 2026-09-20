"""未知字段跳过：解码时遇到 schema 里没有的字段编号，按 wire type 跳过。"""
import pytest

from minipb import wire
from minipb.errors import DecodeError


def _field_varint(number, value):
    return wire.encode_tag(number, wire.WIRE_VARINT) + wire.encode_varint(value)


def _field_len(number, payload):
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return (wire.encode_tag(number, wire.WIRE_LEN)
            + wire.encode_varint(len(payload)) + payload)


def _field_64bit(number, payload8):
    assert len(payload8) == 8
    return wire.encode_tag(number, wire.WIRE_64BIT) + payload8


def _field_32bit(number, payload4):
    assert len(payload4) == 4
    return wire.encode_tag(number, wire.WIRE_32BIT) + payload4


def test_skip_unknown_varint(person_mod):
    Person = person_mod.Person
    data = _field_len(1, "张三".encode("utf-8")) + _field_varint(99, 12345)
    msg = Person.decode(data)
    assert msg.name == "张三"


def test_skip_unknown_all_wire_types(person_mod):
    Person = person_mod.Person
    data = (
        _field_varint(50, 7)                 # wire type 0
        + _field_64bit(51, b"\x01" * 8)      # wire type 1
        + _field_len(52, b"hello")           # wire type 2
        + _field_32bit(53, b"\x02" * 4)      # wire type 5
        + _field_len(1, "abc")               # 已知字段在最后
    )
    msg = Person.decode(data)
    assert msg.name == "abc"


def test_unknown_field_between_known(person_mod):
    Person = person_mod.Person
    data = (
        _field_len(1, "x")                   # name
        + _field_varint(77, 2 ** 64 - 1)     # 未知
        + _field_varint(2, 30)               # age
    )
    msg = Person.decode(data)
    assert msg.name == "x"
    assert msg.age == 30


def test_unknown_nested_message_like(person_mod):
    # 未知字段内容是"嵌套 message 风格"的 length-delimited 数据
    Person = person_mod.Person
    inner = _field_len(1, "junk") + _field_varint(2, 9)
    data = _field_len(1, "y") + _field_len(100, inner)
    msg = Person.decode(data)
    assert msg.name == "y"


def test_unknown_field_invalid_wire_type(person_mod):
    Person = person_mod.Person
    data = _field_len(1, "x") + wire.encode_tag(9, 3)  # wire type 3 非法
    with pytest.raises(DecodeError) as exc:
        Person.decode(data)
    assert "wire type" in str(exc.value)


def test_unknown_field_truncated(person_mod):
    Person = person_mod.Person
    data = _field_len(1, "x") + wire.encode_tag(9, wire.WIRE_64BIT) + b"\x01\x02"
    with pytest.raises(DecodeError):
        Person.decode(data)


def test_roundtrip_preserves_known_ignores_unknown(person_mod):
    # 新版 schema 写入的字段，旧版解码时跳过，已知字段不受影响
    Person = person_mod.Person
    data = Person(name="n", age=5).encode() + _field_len(20, b"future")
    msg = Person.decode(data)
    assert (msg.name, msg.age) == ("n", 5)
