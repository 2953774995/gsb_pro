"""varint / zigzag / tag 的单元测试，以及解码错误处理。"""

import pytest

from minipb import wire
from minipb.errors import DecodeError
from minipb.runtime import Field, Message

VARINT_CASES = [
    (0, b"\x00"),
    (1, b"\x01"),
    (127, b"\x7f"),
    (128, b"\x80\x01"),
    (300, b"\xac\x02"),
    (2 ** 32, b"\x80\x80\x80\x80\x10"),
    (2 ** 64 - 1, b"\xff" * 9 + b"\x01"),
]


@pytest.mark.parametrize("value,expected", VARINT_CASES)
def test_encode_varint(value, expected):
    assert wire.encode_varint(value) == expected


@pytest.mark.parametrize("value,encoded", VARINT_CASES)
def test_decode_varint_roundtrip(value, encoded):
    assert wire.decode_varint(encoded, 0) == (value, len(encoded))


def test_decode_varint_with_offset():
    assert wire.decode_varint(b"\xaa\xac\x02", 1) == (300, 3)


def test_varint_too_long():
    # 11 个字节都带续位标志 -> 超过 10 字节上限
    with pytest.raises(DecodeError) as excinfo:
        wire.decode_varint(b"\x80" * 10 + b"\x01", 0)
    assert excinfo.value.offset == 0
    assert "offset 0" in str(excinfo.value)


def test_varint_truncated():
    with pytest.raises(DecodeError):
        wire.decode_varint(b"\x80", 0)


def test_varint_overflow_64_bits():
    # 10 字节但最高字节 > 1，超出 64 位
    with pytest.raises(DecodeError):
        wire.decode_varint(b"\xff" * 9 + b"\x7f", 0)


class _Int32Msg(Message):
    _fields = [Field("x", 1, "int32", "optional")]


def test_int32_negative_encodes_as_10_byte_varint():
    # int32 负数按 64 位补码编码，占满 10 字节 varint
    data = _Int32Msg(x=-1).encode()
    assert data == b"\x08" + b"\xff" * 9 + b"\x01"
    assert len(data) == 11
    assert _Int32Msg.decode(data).x == -1


def test_int32_min():
    data = _Int32Msg(x=-(2 ** 31)).encode()
    assert data[1:] == b"\x80\x80\x80\x80\xf8\xff\xff\xff\xff\x01"
    assert _Int32Msg.decode(data).x == -(2 ** 31)


ZIGZAG_CASES = [
    (0, 0),
    (-1, 1),
    (1, 2),
    (-2, 3),
    (2, 4),
]


@pytest.mark.parametrize("value,expected", ZIGZAG_CASES)
def test_zigzag_basic(value, expected):
    assert wire.zigzag_encode(value, 32) == expected
    assert wire.zigzag_decode(expected) == value


def test_zigzag_int32_bounds():
    assert wire.zigzag_encode(-(2 ** 31), 32) == 2 ** 32 - 1
    assert wire.zigzag_encode(2 ** 31 - 1, 32) == 2 ** 32 - 2
    assert wire.zigzag_decode(2 ** 32 - 1) == -(2 ** 31)


def test_zigzag_int64_bounds():
    assert wire.zigzag_encode(-(2 ** 63), 64) == 2 ** 64 - 1
    assert wire.zigzag_encode(2 ** 63 - 1, 64) == 2 ** 64 - 2
    assert wire.zigzag_decode(2 ** 64 - 1) == -(2 ** 63)


def test_encode_tag():
    assert wire.encode_tag(1, wire.WIRE_VARINT) == b"\x08"
    assert wire.encode_tag(2, wire.WIRE_LEN) == b"\x12"
    assert wire.encode_tag(2047, wire.WIRE_VARINT) == wire.encode_varint(2047 << 3)


class _StrMsg(Message):
    _fields = [Field("s", 1, "string", "optional")]


def test_decode_invalid_wire_type():
    # tag: field 1, wire type 3（已废弃的 group）-> 非法
    with pytest.raises(DecodeError) as excinfo:
        _StrMsg.decode(bytes([0x0B]))
    assert excinfo.value.offset == 0


def test_decode_length_prefix_too_long():
    # field 1, LEN, 长度 100 但后面没有数据
    data = b"\x0a" + wire.encode_varint(100)
    with pytest.raises(DecodeError) as excinfo:
        _StrMsg.decode(data)
    assert excinfo.value.offset == 1


def test_decode_invalid_utf8():
    data = b"\x0a\x02\xff\xfe"
    with pytest.raises(DecodeError) as excinfo:
        _StrMsg.decode(data)
    assert excinfo.value.offset == 1


def test_decode_field_number_zero():
    with pytest.raises(DecodeError):
        _StrMsg.decode(b"\x00\x01")
