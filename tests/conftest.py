import importlib.util
import sys

import pytest

from minipb.compiler import compile_schema
from minipb.schema import parse

PERSON_SCHEMA = """\
// 示例 schema
message Person {
  required string name = 1;
  optional int32 age = 2;
  repeated string emails = 3;
  optional Address addr = 4;
}

message Address {
  required string city = 1;
  optional int32 zip = 2;
}
"""

ALL_TYPES_SCHEMA = """\
message AllTypes {
  optional int32 i32 = 1;
  optional int64 i64 = 2;
  optional uint32 u32 = 3;
  optional uint64 u64 = 4;
  optional sint32 s32 = 5;
  optional sint64 s64 = 6;
  optional bool flag = 7;
  optional string text = 8;
  optional bytes blob = 9;
  optional double ratio = 10;
  repeated int32 nums = 11;
  repeated string tags = 12;
  repeated double vals = 13;
  optional Inner inner = 14;
  repeated Inner inners = 15;
  required string req = 16;
}

message Inner {
  optional sint64 delta = 1;
  optional bytes raw = 2;
}
"""


def load_generated(tmp_path, schema_text, name="gen_pb"):
    """编译 schema 文本并以模块形式加载生成的 .py 文件。"""
    path = tmp_path / ("%s.py" % name)
    path.write_text(compile_schema(parse(schema_text), source="<test>"),
                    encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def person_mod(tmp_path):
    return load_generated(tmp_path, PERSON_SCHEMA, "person_pb")


@pytest.fixture
def alltypes_mod(tmp_path):
    return load_generated(tmp_path, ALL_TYPES_SCHEMA, "alltypes_pb")
