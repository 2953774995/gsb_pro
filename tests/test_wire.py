"""varint / zigzag / tag 等底层编码规则测试。"""
import pytest

from minipb import wire
from minipb.errors import DecodeError


@pytest.mark.parametrize("value,expected", [
    (0, b"\x00"),
    (1, b"\x01"),
    (127, b"\x7f"),
    (128, b"\x80\x01"),
    (300, b"\xac\x02"),
    (2 ** 32, b"\x80\x80\x80\x80\x10"),
    (2 ** 64 - 1, b"\xff" * 9 + b"\x01"),
])
def test_varint_encode(value, expected):
    assert wire.encode_varint(value) == expected


@pytest.mark.parametrize("value", [0, 1, 127, 128, 300, 2 ** 32, 2 ** 64 - 1])
def test_varint_roundtrip(value):
    data = wire.encode_varint(value)
    decoded, pos = wire.decode_varint(data, 0)
    assert decoded == value
    assert pos == len(data)


def test_varint_decode_with_offset():
    buf = b"\xaa" + wire.encode_varint(300) + b"\xbb"
    value, pos = wire.decode_varint(buf, 1)
    assert value == 300
    assert pos == 3


def test_varint_too_long():
    with pytest.raises(DecodeError) as exc:
        wire.decode_varint(b"\x80" * 10 + b"\x01", 0)
    assert exc.value.offset == 0


def test_varint_truncated():
    with pytest.raises(DecodeError) as exc:
        wire.decode_varint(b"\x80\x80", 0)
    assert exc.value.offset == 0


def test_varint_offset_in_error():
    with pytest.raises(DecodeError) as exc:
        wire.decode_varint(b"\x01\x02\x80", 2)
    assert exc.value.offset == 2


@pytest.mark.parametrize("value,expected", [
    (0, 0), (-1, 1), (1, 2), (-2, 3),
    (2 ** 31 - 1, 2 ** 32 - 2),
    (-(2 ** 31), 2 ** 32 - 1),
])
def test_zigzag32(value, expected):
    assert wire.zigzag_encode(value, 32) == expected
    assert wire.zigzag_decode(expected) == value


@pytest.mark.parametrize("value,expected", [
    (0, 0), (-1, 1), (1, 2), (-2, 3),
    (2 ** 63 - 1, 2 ** 64 - 2),
    (-(2 ** 63), 2 ** 64 - 1),
])
def test_zigzag64(value, expected):
    assert wire.zigzag_encode(value, 64) == expected
    assert wire.zigzag_decode(expected) == value


def test_tag_encoding():
    # 字段 1, wire type 0 -> 0x08；字段 2, wire type 2 -> 0x12
    assert wire.encode_tag(1, 0) == b"\x08"
    assert wire.encode_tag(2, 2) == b"\x12"
    # 字段 16 以上 key 本身也是多字节 varint
    assert wire.encode_tag(2047, 2) == wire.encode_varint(2047 << 3 | 2)


def test_int32_negative_is_10_byte_varint():
    # int32 负数按 64 位补码编码：10 字节 varint
    from minipb.runtime import SCALAR_TYPES
    enc = SCALAR_TYPES["int32"][1]
    assert enc(-1) == b"\xff" * 9 + b"\x01"
    assert len(enc(-1)) == 10
    assert len(enc(-(2 ** 31))) == 10
    dec = SCALAR_TYPES["int32"][2]
    assert dec(b"\xff" * 9 + b"\x01", 0) == (-1, 10)
