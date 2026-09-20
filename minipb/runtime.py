"""运行时：生成的 Python 类继承这里的 Message，编解码逻辑全在这里。"""

import struct

from .errors import DecodeError, EncodeError
from .wire import (
    MASK64,
    WIRE_64BIT,
    WIRE_LEN,
    WIRE_VARINT,
    decode_varint,
    encode_tag,
    encode_varint,
    skip_field,
    zigzag_decode,
    zigzag_encode,
)

MASK32 = (1 << 32) - 1


# ---------------------------------------------------------------------------
# 每种标量类型的编解码器
# ---------------------------------------------------------------------------

class _Codec:
    """encode_raw(v) -> 不带 tag/长度前缀的字节；decode_raw(buf, pos) -> (v, pos)。

    length-delimited 类型的 decode_raw 自己会读长度前缀。
    """

    def __init__(self, wire_type, encode_raw, decode_raw, packable):
        self.wire_type = wire_type
        self.encode_raw = encode_raw
        self.decode_raw = decode_raw
        self.packable = packable


def _check_int(name, value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int):
        raise EncodeError("field %s expects int, got %r" % (name, value))
    if not (lo <= value <= hi):
        raise EncodeError("field %s value %d out of range [%d, %d]" % (name, value, lo, hi))
    return value


def _int_decoder(bits, signed):
    def decode(buf, pos):
        value, pos = decode_varint(buf, pos)
        value &= (1 << bits) - 1
        if signed and value >= 1 << (bits - 1):
            value -= 1 << bits
        return value, pos

    return decode


def _uint_encoder(name, bits):
    def encode(value):
        return encode_varint(_check_int(name, value, 0, (1 << bits) - 1))

    return encode


def _sint_encoder(name, bits):
    def encode(value):
        _check_int(name, value, -(1 << (bits - 1)), (1 << (bits - 1)) - 1)
        return encode_varint(value & MASK64)

    return encode


def _zigzag_encoder(name, bits):
    def encode(value):
        _check_int(name, value, -(1 << (bits - 1)), (1 << (bits - 1)) - 1)
        return encode_varint(zigzag_encode(value, bits))

    return encode


def _zigzag_decoder(buf, pos):
    value, pos = decode_varint(buf, pos)
    return zigzag_decode(value), pos


def _encode_bool(value):
    if not isinstance(value, bool):
        raise EncodeError("bool field expects bool, got %r" % (value,))
    return encode_varint(1 if value else 0)


def _decode_bool(buf, pos):
    value, pos = decode_varint(buf, pos)
    return bool(value & 1), pos


def _encode_double(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EncodeError("double field expects a number, got %r" % (value,))
    return struct.pack("<d", value)


def _decode_double(buf, pos):
    if pos + 8 > len(buf):
        raise DecodeError("truncated double (need 8 bytes)", pos)
    return struct.unpack_from("<d", buf, pos)[0], pos + 8


def _encode_string(value):
    if not isinstance(value, str):
        raise EncodeError("string field expects str, got %r" % (value,))
    return value.encode("utf-8")


def _read_length_delimited(buf, pos):
    start = pos
    length, pos = decode_varint(buf, pos)
    if pos + length > len(buf):
        raise DecodeError(
            "length-delimited field of %d bytes exceeds remaining input" % length,
            start,
        )
    return buf[pos : pos + length], pos + length


def _decode_string(buf, pos):
    start = pos
    raw, pos = _read_length_delimited(buf, pos)
    try:
        return raw.decode("utf-8"), pos
    except UnicodeDecodeError as exc:
        raise DecodeError("invalid utf-8 in string field: %s" % exc, start)


def _encode_bytes(value):
    if not isinstance(value, (bytes, bytearray)):
        raise EncodeError("bytes field expects bytes, got %r" % (value,))
    return bytes(value)


def _decode_bytes(buf, pos):
    return _read_length_delimited(buf, pos)


_CODECS = {
    "int32": _Codec(WIRE_VARINT, _sint_encoder("int32", 32), _int_decoder(32, True), True),
    "int64": _Codec(WIRE_VARINT, _sint_encoder("int64", 64), _int_decoder(64, True), True),
    "uint32": _Codec(WIRE_VARINT, _uint_encoder("uint32", 32), _int_decoder(32, False), True),
    "uint64": _Codec(WIRE_VARINT, _uint_encoder("uint64", 64), _int_decoder(64, False), True),
    "sint32": _Codec(WIRE_VARINT, _zigzag_encoder("sint32", 32), _zigzag_decoder, True),
    "sint64": _Codec(WIRE_VARINT, _zigzag_encoder("sint64", 64), _zigzag_decoder, True),
    "bool": _Codec(WIRE_VARINT, _encode_bool, _decode_bool, True),
    "double": _Codec(WIRE_64BIT, _encode_double, _decode_double, True),
    "string": _Codec(WIRE_LEN, _encode_string, _decode_string, False),
    "bytes": _Codec(WIRE_LEN, _encode_bytes, _decode_bytes, False),
}


# ---------------------------------------------------------------------------
# 字段描述
# ---------------------------------------------------------------------------

class Field:
    """一个字段的描述。msg_type 在生成代码里先是字符串，_resolve 后变成类。"""

    __slots__ = ("name", "number", "type", "label", "msg_type")

    def __init__(self, name, number, type, label, msg_type=None):
        self.name = name
        self.number = number
        self.type = type
        self.label = label
        self.msg_type = msg_type

    @property
    def codec(self):
        if self.type == "message":
            return _message_codec(self.msg_type)
        return _CODECS[self.type]


def _message_codec(msg_cls):
    def encode_raw(value):
        if not isinstance(value, msg_cls):
            raise EncodeError("expected %s, got %r" % (msg_cls.__name__, value))
        return value.encode()

    def decode_raw(buf, pos):
        raw, pos = _read_length_delimited(buf, pos)
        return msg_cls.decode(raw), pos

    return _Codec(WIRE_LEN, encode_raw, decode_raw, False)


# ---------------------------------------------------------------------------
# Message 基类
# ---------------------------------------------------------------------------

class Message:
    """生成的类通过类属性 _fields = [Field(...), ...] 描述自己。"""

    _fields = ()
    _fields_by_number = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._fields_by_number = {f.number: f for f in cls._fields}

    @classmethod
    def _resolve(cls, namespace):
        """把 msg_type 字符串解析成真正的类（支持前向引用）。"""
        for f in cls._fields:
            if f.type == "message" and isinstance(f.msg_type, str):
                try:
                    f.msg_type = namespace[f.msg_type]
                except KeyError:
                    raise EncodeError(
                        "unknown message type %r for field %r" % (f.msg_type, f.name)
                    )

    def __init__(self, **kwargs):
        fields = {f.name: f for f in self._fields}
        for key in kwargs:
            if key not in fields:
                raise TypeError(
                    "%s got an unexpected keyword argument %r"
                    % (type(self).__name__, key)
                )
        for f in self._fields:
            value = kwargs.get(f.name)
            if f.label == "repeated":
                setattr(self, f.name, list(value) if value is not None else [])
            else:
                setattr(self, f.name, value)

    # -- 编码 ---------------------------------------------------------------

    def encode(self):
        out = bytearray()
        for f in self._fields:
            value = getattr(self, f.name)
            codec = f.codec
            if f.label == "repeated":
                if not value:
                    continue
                if codec.packable:
                    payload = b"".join(codec.encode_raw(v) for v in value)
                    out += encode_tag(f.number, WIRE_LEN)
                    out += encode_varint(len(payload))
                    out += payload
                else:
                    for item in value:
                        out += encode_tag(f.number, codec.wire_type)
                        out += _encode_value(codec, item)
            else:
                if value is None:
                    if f.label == "required":
                        raise EncodeError(
                            "required field %r of %s is not set"
                            % (f.name, type(self).__name__)
                        )
                    continue
                out += encode_tag(f.number, codec.wire_type)
                out += _encode_value(codec, value)
        return bytes(out)

    # -- 解码 ---------------------------------------------------------------

    @classmethod
    def decode(cls, data):
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("decode() expects a bytes-like object")
        return cls._decode_from(bytes(data), 0, len(data))

    @classmethod
    def _decode_from(cls, buf, pos, end):
        msg = cls()
        seen = set()
        while pos < end:
            start = pos
            tag, pos = decode_varint(buf, pos)
            field_number = tag >> 3
            wire_type = tag & 7
            if field_number == 0:
                raise DecodeError("invalid field number 0", start)
            field = cls._fields_by_number.get(field_number)
            if field is None:
                # 未知字段：按 wire type 跳过（向前兼容）
                pos = skip_field(buf, pos, wire_type)
                continue
            codec = field.codec
            if field.label == "repeated" and codec.packable and wire_type == WIRE_LEN:
                # packed 编码
                raw, pos = _read_length_delimited(buf, pos)
                values = getattr(msg, field.name)
                sub = 0
                while sub < len(raw):
                    value, sub = codec.decode_raw(raw, sub)
                    values.append(value)
            elif wire_type == codec.wire_type:
                value, pos = codec.decode_raw(buf, pos)
                if field.label == "repeated":
                    getattr(msg, field.name).append(value)
                else:
                    setattr(msg, field.name, value)
                    seen.add(field.name)
            else:
                raise DecodeError(
                    "field %r expects wire type %d, got %d"
                    % (field.name, codec.wire_type, wire_type),
                    start,
                )
            if field.label != "repeated":
                seen.add(field.name)
        for f in cls._fields:
            if f.label == "required" and f.name not in seen:
                raise DecodeError(
                    "required field %r of %s is missing" % (f.name, cls.__name__), end
                )
        return msg

    # -- 杂项 ---------------------------------------------------------------

    def __eq__(self, other):
        if type(self) is not type(other):
            return NotImplemented
        return all(
            getattr(self, f.name) == getattr(other, f.name) for f in self._fields
        )

    def __repr__(self):
        parts = []
        for f in self._fields:
            value = getattr(self, f.name)
            if value is None or (f.label == "repeated" and not value):
                continue
            parts.append("%s=%r" % (f.name, value))
        return "%s(%s)" % (type(self).__name__, ", ".join(parts))


def _encode_value(codec, value):
    raw = codec.encode_raw(value)
    if codec.wire_type == WIRE_LEN:
        return encode_varint(len(raw)) + raw
    return raw
