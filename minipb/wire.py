"""wire format 基础：varint、zigzag、tag。

规则（与 protobuf wire format 一致）:
- varint: 7 位一组，最高位是续位标志，小端序，最多 10 字节（64 位）
- zigzag: sint32/sint64 把有符号数映射成无符号数
- tag = (field_number << 3) | wire_type，编码为 varint
- wire type: 0=varint, 1=64-bit, 2=length-delimited, 5=32-bit
"""

from .errors import DecodeError

WIRE_VARINT = 0
WIRE_64BIT = 1
WIRE_LEN = 2
WIRE_32BIT = 5

MAX_VARINT_BYTES = 10
MASK64 = (1 << 64) - 1


def encode_varint(value):
    """把非负整数编码成 varint。"""
    if value < 0:
        raise ValueError("varint 只能编码非负整数, got %r" % (value,))
    out = bytearray()
    while True:
        bits = value & 0x7F
        value >>= 7
        if value:
            out.append(bits | 0x80)
        else:
            out.append(bits)
            return bytes(out)


def decode_varint(buf, pos):
    """从 buf[pos] 开始解码 varint，返回 (value, new_pos)。

    超过 10 字节、超出 64 位、或缓冲区被截断时抛 DecodeError。
    """
    result = 0
    shift = 0
    start = pos
    for _ in range(MAX_VARINT_BYTES):
        if pos >= len(buf):
            raise DecodeError("truncated varint", start)
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            if result > MASK64:
                raise DecodeError("varint overflows 64 bits", start)
            return result, pos
        shift += 7
    raise DecodeError("varint too long (more than 10 bytes)", start)


def zigzag_encode(value, bits):
    """zigzag 编码: 0->0, -1->1, 1->2, -2->3, ..."""
    return ((value << 1) ^ (value >> (bits - 1))) & ((1 << bits) - 1)


def zigzag_decode(value):
    """zigzag 解码（逆运算）。"""
    return (value >> 1) ^ -(value & 1)


def encode_tag(field_number, wire_type):
    return encode_varint((field_number << 3) | wire_type)


def skip_field(buf, pos, wire_type):
    """按 wire type 跳过一个未知字段，返回新的 pos。"""
    if wire_type == WIRE_VARINT:
        _, pos = decode_varint(buf, pos)
        return pos
    if wire_type == WIRE_64BIT:
        return _checked_skip(buf, pos, 8)
    if wire_type == WIRE_LEN:
        start = pos
        length, pos = decode_varint(buf, pos)
        return _checked_skip(buf, pos, length, start)
    if wire_type == WIRE_32BIT:
        return _checked_skip(buf, pos, 4)
    raise DecodeError("invalid wire type %d" % wire_type, pos)


def _checked_skip(buf, pos, n, start=None):
    if pos + n > len(buf):
        raise DecodeError(
            "field of %d bytes exceeds remaining input" % n,
            pos if start is None else start,
        )
    return pos + n
