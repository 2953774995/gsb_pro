"""required 字段的编码/解码校验。"""

import pytest

from minipb.errors import DecodeError, EncodeError
from minipb.runtime import Field, Message


class Req(Message):
    _fields = [
        Field("name", 1, "string", "required"),
        Field("age", 2, "int32", "optional"),
    ]


def test_encode_required_missing():
    with pytest.raises(EncodeError) as excinfo:
        Req().encode()
    assert "required" in str(excinfo.value)
    assert "name" in str(excinfo.value)


def test_decode_required_missing():
    # 只有字段 2，没有 required 的字段 1
    data = b"\x10\x2a"
    with pytest.raises(DecodeError) as excinfo:
        Req.decode(data)
    assert "required" in str(excinfo.value)


def test_required_ok():
    msg = Req(name="张三", age=30)
    assert Req.decode(msg.encode()) == msg


def test_encode_error_on_bad_type():
    with pytest.raises(EncodeError):
        Req(name="x", age="not an int").encode()
    with pytest.raises(EncodeError):
        Req(name="x", age=2 ** 40).encode()  # int32 越界
