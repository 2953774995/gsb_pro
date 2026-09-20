"""schema 解析错误：重复编号、未知类型、缺分号等，报错都要带行号。"""

import pytest

from minipb.errors import SchemaError
from minipb.schema import parse_schema


def test_duplicate_field_number():
    text = """
message M {
  optional int32 a = 1;
  optional int32 b = 1;
}
"""
    with pytest.raises(SchemaError) as excinfo:
        parse_schema(text)
    assert excinfo.value.line == 4
    assert "line 4" in str(excinfo.value)
    assert "duplicate field number" in str(excinfo.value)


def test_unknown_type():
    text = """
message M {
  optional NoSuchType x = 1;
}
"""
    with pytest.raises(SchemaError) as excinfo:
        parse_schema(text)
    assert excinfo.value.line == 3
    assert "unknown type" in str(excinfo.value)


def test_missing_semicolon():
    text = """
message M {
  optional int32 a = 1
  optional int32 b = 2;
}
"""
    with pytest.raises(SchemaError) as excinfo:
        parse_schema(text)
    assert excinfo.value.line == 4
    assert "expected" in str(excinfo.value)


def test_field_number_out_of_range():
    with pytest.raises(SchemaError) as excinfo:
        parse_schema("message M { optional int32 a = 2048; }")
    assert "out of range" in str(excinfo.value)
    # 边界：2047 合法
    parse_schema("message M { optional int32 a = 2047; }")


def test_field_number_zero():
    with pytest.raises(SchemaError):
        parse_schema("message M { optional int32 a = 0; }")


def test_duplicate_message_name():
    text = "message A {}\nmessage A {}\n"
    with pytest.raises(SchemaError) as excinfo:
        parse_schema(text)
    assert excinfo.value.line == 2


def test_missing_brace():
    with pytest.raises(SchemaError) as excinfo:
        parse_schema("message M { optional int32 a = 1;")
    assert "missing '}'" in str(excinfo.value)


def test_bad_label():
    with pytest.raises(SchemaError) as excinfo:
        parse_schema("message M { mandatory int32 a = 1; }")
    assert "required/optional/repeated" in str(excinfo.value)


def test_forward_reference_ok():
    text = """
message A { optional B b = 1; }
message B { optional int32 x = 1; }
"""
    schema = parse_schema(text)
    assert [m.name for m in schema.messages] == ["A", "B"]


def test_comments_and_empty_schema():
    parse_schema("// just a comment\nmessage M {\n  // field\n  optional int32 a = 1;\n}\n")
    with pytest.raises(SchemaError):
        parse_schema("// nothing here\n")
