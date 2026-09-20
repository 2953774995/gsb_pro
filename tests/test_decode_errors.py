"""解码错误处理：都必须抛 DecodeError 并带字节偏移。"""
import pytest

from minipb import wire
from minipb.errors import DecodeError


def test_varint_over_10_bytes(person_mod):
    Person = person_mod.Person
    # 字段 2 (age, varint) 的值是 11 字节的 varint
    data = wire.encode_tag(2, 0) + b"\x80" * 10 + b"\x01"
    with pytest.raises(DecodeError) as exc:
        Person.decode(data)
    assert exc.value.offset == 1  # varint 起始位置


def test_truncated_varint(person_mod):
    Person = person_mod.Person
    data = wire.encode_tag(2, 0) + b"\x80\x80"
    with pytest.raises(DecodeError) as exc:
        Person.decode(data)
    assert exc.value.offset == 1


def test_length_prefix_too_long(person_mod):
    Person = person_mod.Person
    # 字段 1 (name, string) 声明长度 100，但后面没有数据
    data = wire.encode_tag(1, 2) + wire.encode_varint(100) + b"ab"
    with pytest.raises(DecodeError) as exc:
        Person.decode(data)
    assert exc.value.offset == 2  # 长度前缀之后的位置
    assert "100" in str(exc.value)


def test_invalid_wire_type(person_mod):
    Person = person_mod.Person
    data = wire.encode_tag(1, 7)  # wire type 7 不存在
    with pytest.raises(DecodeError) as exc:
        Person.decode(data)
    assert exc.value.offset == 1


def test_field_number_zero(person_mod):
    Person = person_mod.Person
    with pytest.raises(DecodeError) as exc:
        Person.decode(b"\x00\x01")
    assert exc.value.offset == 1


def test_utf8_decode_failure(person_mod):
    Person = person_mod.Person
    bad_utf8 = b"\xff\xfe"
    data = (wire.encode_tag(1, 2) + wire.encode_varint(len(bad_utf8))
            + bad_utf8)
    with pytest.raises(DecodeError) as exc:
        Person.decode(data)
    assert exc.value.offset == 2  # 字符串内容起始位置
    assert "utf-8" in str(exc.value)


def test_nested_error_offset_is_outer(person_mod):
    # 嵌套 message 内部的错误，偏移要换算成外层缓冲区偏移
    Person = person_mod.Person
    inner = wire.encode_tag(1, 2) + wire.encode_varint(50) + b"x"  # 长度超长
    data = (wire.encode_tag(1, 2) + wire.encode_varint(1) + b"n"   # name="n"
            + wire.encode_tag(4, 2) + wire.encode_varint(len(inner)) + inner)
    with pytest.raises(DecodeError) as exc:
        Person.decode(data)
    # 外层 addr 内容从 offset 5 开始，内部错误在 offset 1
    assert exc.value.offset == 5 + 1


def test_truncated_tag(person_mod):
    Person = person_mod.Person
    with pytest.raises(DecodeError):
        Person.decode(b"\x80")  # tag 的 varint 没写完


def test_wrong_wire_type_for_known_field(person_mod):
    Person = person_mod.Person
    # name 是 string(wire 2)，这里给了 varint(wire 0)
    data = wire.encode_tag(1, 0) + wire.encode_varint(5)
    with pytest.raises(DecodeError) as exc:
        Person.decode(data)
    assert "wire type" in str(exc.value)


def test_decode_error_attributes(person_mod):
    Person = person_mod.Person
    try:
        Person.decode(b"\x0a\x05ab")
    except DecodeError as e:
        assert isinstance(e.offset, int)
        assert "offset" in str(e)
    else:
        raise AssertionError("应该抛 DecodeError")
