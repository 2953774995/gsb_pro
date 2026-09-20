"""schema 解析：正常解析 + 各类带行号的错误。"""
import pytest

from minipb.errors import SchemaError
from minipb.schema import parse


def test_parse_basic():
    schema = parse("""
message Person {
  required string name = 1;
  optional int32 age = 2;
  repeated string emails = 3;
}
""")
    assert [m.name for m in schema.messages] == ["Person"]
    person = schema.messages[0]
    assert [(f.label, f.type_name, f.name, f.number) for f in person.fields] == [
        ("required", "string", "name", 1),
        ("optional", "int32", "age", 2),
        ("repeated", "string", "emails", 3),
    ]


def test_parse_multiple_messages_and_comments():
    schema = parse("""
// 行注释
message A {
  required string x = 1;  // 尾部注释
}
/* 块注释
   跨行 */
message B {
  optional A a = 1;
}
""")
    assert [m.name for m in schema.messages] == ["A", "B"]
    assert schema.messages[1].fields[0].type_name == "A"


def test_duplicate_field_number():
    with pytest.raises(SchemaError) as exc:
        parse("message M {\n  optional int32 a = 1;\n  optional int32 b = 1;\n}")
    assert exc.value.line == 3
    assert "重复" in str(exc.value)


def test_unknown_type():
    with pytest.raises(SchemaError) as exc:
        parse("message M {\n  optional FooBar x = 1;\n}")
    assert exc.value.line == 2
    assert "FooBar" in str(exc.value)


def test_missing_semicolon():
    with pytest.raises(SchemaError) as exc:
        parse("message M {\n  optional int32 a = 1\n  optional int32 b = 2;\n}")
    assert exc.value.line == 2
    assert ";" in str(exc.value)


def test_missing_brace():
    with pytest.raises(SchemaError) as exc:
        parse("message M {\n  optional int32 a = 1;\n")
    assert exc.value.line == 2


def test_field_number_out_of_range():
    with pytest.raises(SchemaError) as exc:
        parse("message M {\n  optional int32 a = 2048;\n}")
    assert exc.value.line == 2
    with pytest.raises(SchemaError):
        parse("message M { optional int32 a = 0; }")


def test_duplicate_message_name():
    with pytest.raises(SchemaError) as exc:
        parse("message M { optional int32 a = 1; }\nmessage M { optional int32 b = 1; }")
    assert exc.value.line == 2


def test_duplicate_field_name():
    with pytest.raises(SchemaError) as exc:
        parse("message M {\n  optional int32 a = 1;\n  optional string a = 2;\n}")
    assert exc.value.line == 3


def test_bad_label():
    with pytest.raises(SchemaError) as exc:
        parse("message M {\n  mandatory int32 a = 1;\n}")
    assert exc.value.line == 2


def test_empty_schema():
    with pytest.raises(SchemaError):
        parse("   \n// nothing\n")


def test_forward_reference_allowed():
    schema = parse("""
message A { optional B b = 1; }
message B { optional int32 x = 1; }
""")
    assert schema.messages[0].fields[0].type_name == "B"


def test_max_field_number_ok():
    schema = parse("message M { optional int32 a = 2047; }")
    assert schema.messages[0].fields[0].number == 2047
