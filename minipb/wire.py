"""底层 wire format：varint、zigzag、tag、字段跳过。

规则与 Protocol Buffers 一致：
- varint：7 位一组，最高位是续位标志，小端序，最多 10 字节（64 位）。
- zigzag：sint32/sint64 把负数映射成正数。
- wire type：0=varint, 1=64-bit, 2=length-delimited, 5=32-bit。
"""

from .errors import DecodeError

WIRE_VARINT = 0
WIRE_64BIT = 1
WIRE_LEN = 2
WIRE_32BIT = 5

MAX_VARINT_BYTES = 10


def encode_varint(value):
    """非负整数 -> varint 字节串。"""
    if value < 0:
        raise ValueError("varint 只能编码非负整数，得到 %r" % (value,))
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
    """从 buf[pos] 解码 varint，返回 (value, new_pos)。

    超过 10 字节或缓冲区被截断时抛 DecodeError（带偏移）。
    """
    result = 0
    shift = 0
    start = pos
    while True:
        if pos >= len(buf):
            raise DecodeError("varint 被截断（缓冲区结束但续位仍置位）", start)
        if pos - start >= MAX_VARINT_BYTES:
            raise DecodeError("varint 超过 10 字节", start)
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7


def zigzag_encode(value, bits):
    """zigzag：0->0, -1->1, 1->2, -2->3 ..."""
    mask = (1 << bits) - 1
    return ((value << 1) ^ (value >> (bits - 1))) & mask


def zigzag_decode(value):
    """zigzag 解码（32/64 位通用，符号由最低位决定）。"""
    return (value >> 1) ^ -(value & 1)


def encode_tag(field_number, wire_type):
    """字段 key = (field_number << 3) | wire_type，编码为 varint。"""
    return encode_varint((field_number << 3) | wire_type)


def read_length_delimited(buf, pos):
    """读长度前缀 + 内容，返回 (bytes, new_pos)。长度超长抛 DecodeError。"""
    length, pos = decode_varint(buf, pos)
    remaining = len(buf) - pos
    if length > remaining:
        raise DecodeError(
            "长度前缀 %d 超出剩余缓冲区（仅剩 %d 字节）" % (length, remaining),
            pos)
    return bytes(buf[pos:pos + length]), pos + length


def skip_field(buf, pos, wire_type):
    """按 wire type 跳过一个未知字段，返回新位置。"""
    if wire_type == WIRE_VARINT:
        _, pos = decode_varint(buf, pos)
        return pos
    if wire_type == WIRE_64BIT:
        if pos + 8 > len(buf):
            raise DecodeError("64-bit 字段被截断", pos)
        return pos + 8
    if wire_type == WIRE_LEN:
        _, pos = read_length_delimited(buf, pos)
        return pos
    if wire_type == WIRE_32BIT:
        if pos + 4 > len(buf):
            raise DecodeError("32-bit 字段被截断", pos)
        return pos + 4
    raise DecodeError("非法 wire type %d（合法值：0/1/2/5）" % wire_type, pos)
