"""minipb 运行时：Message 基类、Field 描述、标量类型编解码表。

生成的 *_pb.py 文件只需要声明：

    class Person(Message):
        _fields_ = [
            Field("name", "string", "required", 1),
            ...
        ]

所有编码/解码逻辑都集中在这里，生成代码保持极简、可读。
"""

import struct
import sys

from . import wire
from .errors import DecodeError, EncodeError

_INT32_MIN, _INT32_MAX = -(2 ** 31), 2 ** 31 - 1
_INT64_MIN, _INT64_MAX = -(2 ** 63), 2 ** 63 - 1
_UINT32_MAX = 2 ** 32 - 1
_UINT64_MAX = 2 ** 64 - 1
_MASK32 = 2 ** 32 - 1
_MASK64 = 2 ** 64 - 1


def _check_int(name, value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int):
        raise EncodeError("字段类型 %s 需要 int，得到 %r" % (name, value))
    if not (lo <= value <= hi):
        raise EncodeError(
            "字段类型 %s 数值越界：%d 不在 [%d, %d]" % (name, value, lo, hi))
    return value


def _range_encoder(name, lo, hi, raw_enc):
    def enc(v):
        return raw_enc(_check_int(name, v, lo, hi))
    return enc


# --- int32：负数按 64 位补码编码成 10 字节 varint（与 protobuf 一致） ---

def _enc_int32(v):
    return wire.encode_varint(v & _MASK64 if v < 0 else v)


def _dec_int32(buf, pos):
    v, pos = wire.decode_varint(buf, pos)
    v &= _MASK32
    return (v - 2 ** 32 if v >= 2 ** 31 else v), pos


def _enc_int64(v):
    return wire.encode_varint(v & _MASK64 if v < 0 else v)


def _dec_int64(buf, pos):
    v, pos = wire.decode_varint(buf, pos)
    v &= _MASK64
    return (v - 2 ** 64 if v >= 2 ** 63 else v), pos


def _enc_uint32(v):
    return wire.encode_varint(v)


def _dec_uint32(buf, pos):
    v, pos = wire.decode_varint(buf, pos)
    return v & _MASK32, pos


def _enc_uint64(v):
    return wire.encode_varint(v)


def _dec_uint64(buf, pos):
    v, pos = wire.decode_varint(buf, pos)
    return v & _MASK64, pos


def _enc_sint32(v):
    return wire.encode_varint(wire.zigzag_encode(v, 32))


def _dec_sint32(buf, pos):
    v, pos = wire.decode_varint(buf, pos)
    return wire.zigzag_decode(v & _MASK32), pos


def _enc_sint64(v):
    return wire.encode_varint(wire.zigzag_encode(v, 64))


def _dec_sint64(buf, pos):
    v, pos = wire.decode_varint(buf, pos)
    return wire.zigzag_decode(v & _MASK64), pos


def _enc_bool(v):
    if not isinstance(v, (bool, int)):
        raise EncodeError("字段类型 bool 需要 bool，得到 %r" % (v,))
    return b"\x01" if v else b"\x00"


def _dec_bool(buf, pos):
    v, pos = wire.decode_varint(buf, pos)
    return (v != 0), pos


def _enc_double(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise EncodeError("字段类型 double 需要数值，得到 %r" % (v,))
    return struct.pack("<d", float(v))


def _dec_double(buf, pos):
    if pos + 8 > len(buf):
        raise DecodeError("double 字段被截断（不足 8 字节）", pos)
    return struct.unpack_from("<d", buf, pos)[0], pos + 8


def _enc_string(v):
    if not isinstance(v, str):
        raise EncodeError("字段类型 string 需要 str，得到 %r" % (v,))
    data = v.encode("utf-8")
    return wire.encode_varint(len(data)) + data


def _dec_string(buf, pos):
    raw, pos = wire.read_length_delimited(buf, pos)
    try:
        return raw.decode("utf-8"), pos
    except UnicodeDecodeError as e:
        raise DecodeError("string 字段 utf-8 解码失败：%s" % e,
                          pos - len(raw))


def _enc_bytes(v):
    if not isinstance(v, (bytes, bytearray)):
        raise EncodeError("字段类型 bytes 需要 bytes，得到 %r" % (v,))
    v = bytes(v)
    return wire.encode_varint(len(v)) + v


def _dec_bytes(buf, pos):
    return wire.read_length_delimited(buf, pos)


# type_name -> (wire_type, encode, decode, packable)
SCALAR_TYPES = {
    "int32":  (wire.WIRE_VARINT, _range_encoder("int32", _INT32_MIN, _INT32_MAX, _enc_int32), _dec_int32, True),
    "int64":  (wire.WIRE_VARINT, _range_encoder("int64", _INT64_MIN, _INT64_MAX, _enc_int64), _dec_int64, True),
    "uint32": (wire.WIRE_VARINT, _range_encoder("uint32", 0, _UINT32_MAX, _enc_uint32), _dec_uint32, True),
    "uint64": (wire.WIRE_VARINT, _range_encoder("uint64", 0, _UINT64_MAX, _enc_uint64), _dec_uint64, True),
    "sint32": (wire.WIRE_VARINT, _range_encoder("sint32", _INT32_MIN, _INT32_MAX, _enc_sint32), _dec_sint32, True),
    "sint64": (wire.WIRE_VARINT, _range_encoder("sint64", _INT64_MIN, _INT64_MAX, _enc_sint64), _dec_sint64, True),
    "bool":   (wire.WIRE_VARINT, _enc_bool, _dec_bool, True),
    "string": (wire.WIRE_LEN, _enc_string, _dec_string, False),
    "bytes":  (wire.WIRE_LEN, _enc_bytes, _dec_bytes, False),
    "double": (wire.WIRE_64BIT, _enc_double, _dec_double, True),
}


class Field(object):
    """字段描述：名字、类型名、修饰（required/optional/repeated）、编号。"""

    __slots__ = ("name", "type_name", "label", "number")

    def __init__(self, name, type_name, label, number):
        if label not in ("required", "optional", "repeated"):
            raise ValueError("非法字段修饰 %r" % (label,))
        self.name = name
        self.type_name = type_name
        self.label = label
        self.number = number

    @property
    def is_scalar(self):
        return self.type_name in SCALAR_TYPES

    @property
    def packable(self):
        return self.is_scalar and SCALAR_TYPES[self.type_name][3]

    def __repr__(self):
        return "Field(%r, %r, %r, %d)" % (
            self.name, self.type_name, self.label, self.number)


def _resolve_message(owner_cls, type_name):
    """在定义 owner_cls 的模块里按名字查找嵌套 message 类。"""
    module = sys.modules.get(owner_cls.__module__)
    cls = getattr(module, type_name, None) if module is not None else None
    if not (isinstance(cls, type) and issubclass(cls, Message)):
        raise EncodeError("未知 message 类型 %r（在模块 %s 中找不到）"
                          % (type_name, owner_cls.__module__))
    return cls


class Message(object):
    """所有生成 message 类的基类。子类需定义 _fields_ = [Field(...), ...]"""

    _fields_ = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._fields_by_number = {}
        cls._fields_by_name = {}
        for f in cls._fields_:
            if f.number in cls._fields_by_number:
                raise ValueError("message %s 字段编号 %d 重复"
                                 % (cls.__name__, f.number))
            cls._fields_by_number[f.number] = f
            cls._fields_by_name[f.name] = f

    def __init__(self, **kwargs):
        object.__setattr__(self, "_present", set())
        for f in self._fields_:
            object.__setattr__(self, f.name,
                               [] if f.label == "repeated" else None)
        for key, value in kwargs.items():
            if key not in self._fields_by_name:
                raise TypeError("%s 没有字段 %r" % (type(self).__name__, key))
            setattr(self, key, value)

    def __setattr__(self, name, value):
        f = self._fields_by_name.get(name)
        if f is None:
            raise AttributeError("%s 没有字段 %r" % (type(self).__name__, name))
        if f.label == "repeated":
            value = list(value)
        else:
            self._present.add(name)
        object.__setattr__(self, name, value)

    # ---------------------------------------------------------------- 编码

    def encode(self):
        """编码为紧凑二进制。required 字段未赋值时抛 EncodeError。"""
        out = bytearray()
        for f in sorted(self._fields_, key=lambda f: f.number):
            if f.label == "repeated":
                values = getattr(self, f.name)
                if not values:
                    continue
                if f.packable:
                    # packed：wire type 2，长度前缀 + 所有值直接拼接
                    _, enc, _, _ = SCALAR_TYPES[f.type_name]
                    payload = b"".join(enc(v) for v in values)
                    out += wire.encode_tag(f.number, wire.WIRE_LEN)
                    out += wire.encode_varint(len(payload))
                    out += payload
                else:
                    for v in values:
                        out += self._encode_single(f, v)
            else:
                if f.name not in self._present:
                    if f.label == "required":
                        raise EncodeError(
                            "required 字段 %r 未赋值，无法编码 %s"
                            % (f.name, type(self).__name__))
                    continue
                out += self._encode_single(f, getattr(self, f.name))
        return bytes(out)

    def _encode_single(self, f, value):
        if f.is_scalar:
            wt, enc, _, _ = SCALAR_TYPES[f.type_name]
            return wire.encode_tag(f.number, wt) + enc(value)
        sub = _resolve_message(type(self), f.type_name)
        if not isinstance(value, sub):
            raise EncodeError("字段 %r 需要 %s 实例，得到 %r"
                              % (f.name, f.type_name, value))
        payload = value.encode()
        return (wire.encode_tag(f.number, wire.WIRE_LEN)
                + wire.encode_varint(len(payload)) + payload)

    # ---------------------------------------------------------------- 解码

    @classmethod
    def decode(cls, data):
        """从 bytes 解码。未知字段按 wire type 跳过（向前兼容）。"""
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("decode 需要 bytes，得到 %r" % (data,))
        data = bytes(data)
        msg = cls()
        pos = 0
        n = len(data)
        while pos < n:
            key, pos = wire.decode_varint(data, pos)
            number = key >> 3
            wt = key & 7
            if number == 0:
                raise DecodeError("非法字段编号 0", pos)
            f = cls._fields_by_number.get(number)
            if f is None:
                pos = wire.skip_field(data, pos, wt)
                continue
            pos = cls._decode_field(msg, f, wt, data, pos)
        for f in cls._fields_:
            if f.label == "required" and f.name not in msg._present:
                raise DecodeError(
                    "required 字段 %r 在数据中缺失" % f.name, len(data))
        return msg

    @classmethod
    def _decode_field(cls, msg, f, wt, data, pos):
        if f.is_scalar:
            natural_wt, _, dec, packable = SCALAR_TYPES[f.type_name]
            if f.label == "repeated" and packable and wt == wire.WIRE_LEN:
                # packed 编码的 repeated 数值字段
                payload, pos = wire.read_length_delimited(data, pos)
                values = getattr(msg, f.name)
                ppos = 0
                while ppos < len(payload):
                    v, ppos = dec(payload, ppos)
                    values.append(v)
                return pos
            if wt != natural_wt:
                raise DecodeError(
                    "字段 %r wire type 错误：期望 %d，得到 %d"
                    % (f.name, natural_wt, wt), pos)
            value, pos = dec(data, pos)
        else:
            if wt != wire.WIRE_LEN:
                raise DecodeError(
                    "message 字段 %r wire type 错误：期望 2，得到 %d"
                    % (f.name, wt), pos)
            sub_cls = _resolve_message(cls, f.type_name)
            payload, end = wire.read_length_delimited(data, pos)
            try:
                value = sub_cls.decode(payload)
            except DecodeError as e:
                # 把嵌套 message 内的偏移换算成外层偏移
                raise DecodeError("字段 %r 内：%s" % (f.name, e.message),
                                  pos + e.offset)
            pos = end
        if f.label == "repeated":
            getattr(msg, f.name).append(value)
        else:
            setattr(msg, f.name, value)
        return pos

    # ---------------------------------------------------------------- 杂项

    def __eq__(self, other):
        if type(self) is not type(other):
            return NotImplemented
        return (all(getattr(self, f.name) == getattr(other, f.name)
                    for f in self._fields_)
                and self._present == other._present)

    def __ne__(self, other):
        eq = self.__eq__(other)
        return eq if eq is NotImplemented else not eq

    def __repr__(self):
        parts = []
        for f in self._fields_:
            if f.label == "repeated":
                if getattr(self, f.name):
                    parts.append("%s=%r" % (f.name, getattr(self, f.name)))
            elif f.name in self._present:
                parts.append("%s=%r" % (f.name, getattr(self, f.name)))
        return "%s(%s)" % (type(self).__name__, ", ".join(parts))
