"""所有字段类型、嵌套 message、repeated、空值的 roundtrip 测试。"""

import importlib.util
import sys

import pytest

from minipb.cli import main as cli_main

SCHEMA = """
message Inner {
  required string label = 1;
  optional int32 n = 2;
}

message Empty {
}

message AllTypes {
  required int32 i32 = 1;
  optional int64 i64 = 2;
  optional uint32 u32 = 3;
  optional uint64 u64 = 4;
  optional sint32 s32 = 5;
  optional sint64 s64 = 6;
  optional bool flag = 7;
  optional string text = 8;
  optional bytes blob = 9;
  optional double ratio = 10;
  optional Inner inner = 11;
  repeated int32 nums = 12;
  repeated string tags = 13;
  repeated Inner inners = 14;
  repeated double scores = 15;
}
"""


@pytest.fixture(scope="module")
def mod(tmp_path_factory):
    """把 SCHEMA 编译成 .py 并动态加载（走真实 CLI 路径）。"""
    tmp = tmp_path_factory.mktemp("roundtrip")
    mpb = tmp / "all.mpb"
    mpb.write_text(SCHEMA, encoding="utf-8")
    out = tmp / "all_pb.py"
    assert cli_main(["compile", str(mpb), "-o", str(out)]) == 0
    spec = importlib.util.spec_from_file_location("all_pb", str(out))
    module = importlib.util.module_from_spec(spec)
    sys.modules["all_pb"] = module
    spec.loader.exec_module(module)
    return module


def test_all_scalar_types_roundtrip(mod):
    msg = mod.AllTypes(
        i32=-(2 ** 31),
        i64=-(2 ** 63),
        u32=2 ** 32 - 1,
        u64=2 ** 64 - 1,
        s32=-12345,
        s64=2 ** 62,
        flag=True,
        text="张三 hello",
        blob=b"\x00\xff\x10binary",
        ratio=3.141592653589793,
    )
    data = msg.encode()
    back = mod.AllTypes.decode(data)
    assert back == msg
    assert back.i32 == -(2 ** 31)
    assert back.i64 == -(2 ** 63)
    assert back.u32 == 2 ** 32 - 1
    assert back.u64 == 2 ** 64 - 1
    assert back.s32 == -12345
    assert back.s64 == 2 ** 62
    assert back.flag is True
    assert back.text == "张三 hello"
    assert back.blob == b"\x00\xff\x10binary"
    assert back.ratio == 3.141592653589793


def test_optional_unset_not_encoded(mod):
    msg = mod.AllTypes(i32=1)
    data = msg.encode()
    assert data == b"\x08\x01"  # 只有 required 的 i32
    back = mod.AllTypes.decode(data)
    assert back.i64 is None
    assert back.text is None
    assert back.blob is None
    assert back.inner is None
    assert back.nums == []
    assert back.tags == []


def test_nested_message_roundtrip(mod):
    msg = mod.AllTypes(
        i32=7,
        inner=mod.Inner(label="城市", n=-3),
        inners=[mod.Inner(label="a"), mod.Inner(label="b", n=9)],
    )
    back = mod.AllTypes.decode(msg.encode())
    assert back == msg
    assert back.inner.label == "城市"
    assert back.inner.n == -3
    assert [i.label for i in back.inners] == ["a", "b"]
    assert back.inners[1].n == 9


def test_repeated_numeric_uses_packed_encoding(mod):
    msg = mod.AllTypes(i32=0, nums=[1, 300, -1])
    data = msg.encode()
    # field 1: i32=0 -> 08 00；field 12 packed: tag = (12<<3)|2 = 0x62
    assert data[:2] == b"\x08\x00"
    assert data[2] == 0x62
    length = data[3]
    payload = data[4 : 4 + length]
    assert len(payload) == length
    assert mod.AllTypes.decode(data).nums == [1, 300, -1]


def test_repeated_string_not_packed(mod):
    msg = mod.AllTypes(i32=0, tags=["x", "yz"])
    data = msg.encode()
    # 每个 string 单独一个 tag: (13<<3)|2 = 0x6a
    assert data == b"\x08\x00" + b"\x6a\x01x" + b"\x6a\x02yz"
    assert mod.AllTypes.decode(data).tags == ["x", "yz"]


def test_decode_unpacked_repeated_numeric(mod):
    # 非 packed 形式（每个元素一个 tag）也要能解码：field 12, wire type 0
    data = b"\x08\x00" + b"\x60\x01" + b"\x60\xac\x02" + b"\x60\x03"
    back = mod.AllTypes.decode(data)
    assert back.nums == [1, 300, 3]


def test_repeated_double_packed(mod):
    msg = mod.AllTypes(i32=0, scores=[1.5, -2.25, 0.0])
    data = msg.encode()
    # tag = (15<<3)|2 = 0x7a, 长度 24
    assert b"\x7a\x18" in data
    assert mod.AllTypes.decode(data).scores == [1.5, -2.25, 0.0]


def test_empty_message_roundtrip(mod):
    assert mod.Empty().encode() == b""
    assert mod.Empty.decode(b"") == mod.Empty()


def test_empty_string_and_bytes_roundtrip(mod):
    msg = mod.AllTypes(i32=0, text="", blob=b"")
    back = mod.AllTypes.decode(msg.encode())
    assert back.text == ""
    assert back.blob == b""


def test_empty_repeated_not_encoded(mod):
    msg = mod.AllTypes(i32=0, nums=[], tags=[])
    assert msg.encode() == b"\x08\x00"


def test_encode_is_byte_stable(mod):
    msg = mod.AllTypes(
        i32=42, text="稳定", nums=[1, 2, 3], inner=mod.Inner(label="x")
    )
    assert msg.encode() == msg.encode()
    assert mod.AllTypes.decode(msg.encode()).encode() == msg.encode()


def test_unknown_kwarg_rejected(mod):
    with pytest.raises(TypeError):
        mod.AllTypes(i32=1, nope=2)
