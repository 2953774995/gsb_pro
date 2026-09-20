"""编解码 roundtrip：所有字段类型、嵌套 message、repeated、边界值。"""
import pytest

from minipb.errors import DecodeError, EncodeError


def test_person_roundtrip(person_mod):
    Person, Address = person_mod.Person, person_mod.Address
    msg = Person(name="张三", age=30,
                 emails=["a@x.com", "b@y.com"],
                 addr=Address(city="上海", zip=200000))
    data = msg.encode()
    back = Person.decode(data)
    assert back == msg
    assert back.name == "张三"
    assert back.age == 30
    assert back.emails == ["a@x.com", "b@y.com"]
    assert back.addr.city == "上海"
    assert back.addr.zip == 200000


def test_byte_level_stability(person_mod):
    # 自己跟自己 roundtrip 必须字节级稳定：decode 后再 encode 得到相同字节
    Person, Address = person_mod.Person, person_mod.Address
    msg = Person(name="张三", age=30, emails=["a@x.com"],
                 addr=Address(city="上海"))
    data = msg.encode()
    assert Person.decode(data).encode() == data


def test_optional_unset_not_encoded(person_mod):
    Person = person_mod.Person
    msg = Person(name="x")
    data = msg.encode()
    # 只有字段 1：tag 0x0a + 长度 1 + 'x'
    assert data == b"\x0a\x01x"
    back = Person.decode(data)
    assert back.age is None
    assert back.emails == []
    assert back.addr is None


def test_optional_zero_value_is_encoded(person_mod):
    # optional 显式赋 0 也要编码（presence 语义）
    Person = person_mod.Person
    msg = Person(name="x", age=0)
    data = msg.encode()
    assert b"\x10\x00" in data  # 字段 2, varint 0
    assert Person.decode(data).age == 0


def test_required_missing_raises(person_mod):
    Person = person_mod.Person
    with pytest.raises(EncodeError, match="required"):
        Person(age=30).encode()


def test_required_missing_on_decode(person_mod):
    Person = person_mod.Person
    # 只有字段 2（age），没有 required 的 name
    with pytest.raises(DecodeError, match="required"):
        Person.decode(b"\x10\x1e")


def test_all_scalar_types(alltypes_mod):
    AllTypes = alltypes_mod.AllTypes
    msg = AllTypes(
        req="r",
        i32=-(2 ** 31), i64=-(2 ** 63),
        u32=2 ** 32 - 1, u64=2 ** 64 - 1,
        s32=-123456, s64=2 ** 62,
        flag=True, text="héllo 世界", blob=b"\x00\xff\x01",
        ratio=3.141592653589793,
    )
    back = AllTypes.decode(msg.encode())
    assert back == msg
    assert back.i32 == -(2 ** 31)
    assert back.u64 == 2 ** 64 - 1
    assert back.ratio == 3.141592653589793


def test_repeated_packed_numeric(alltypes_mod):
    AllTypes = alltypes_mod.AllTypes
    msg = AllTypes(req="r", nums=[1, 300, -5], vals=[1.5, -2.5])
    data = msg.encode()
    # nums 是字段 11，packed：tag = 11<<3|2 = 0x5a
    assert b"\x5a" in data
    back = AllTypes.decode(data)
    assert back.nums == [1, 300, -5]
    assert back.vals == [1.5, -2.5]


def test_repeated_nonpacked_string_and_message(alltypes_mod):
    AllTypes, Inner = alltypes_mod.AllTypes, alltypes_mod.Inner
    msg = AllTypes(req="r", tags=["a", "b", "c"],
                   inners=[Inner(delta=1), Inner(delta=-2, raw=b"x")])
    back = AllTypes.decode(msg.encode())
    assert back.tags == ["a", "b", "c"]
    assert [i.delta for i in back.inners] == [1, -2]
    assert back.inners[1].raw == b"x"


def test_packed_wireformat_exact(alltypes_mod):
    # packed int32 [1, 300]：tag 0x5a, len 3, 01 ac 02
    AllTypes = alltypes_mod.AllTypes
    data = AllTypes(req="r", nums=[1, 300]).encode()
    assert b"\x5a\x03\x01\xac\x02" in data


def test_decode_accepts_unpacked_repeated(alltypes_mod):
    # 解码端要兼容非 packed 写法（逐字段）
    AllTypes = alltypes_mod.AllTypes
    # 字段 11 varint：tag = 11<<3|0 = 0x58，值 1 和 2
    data = b"\x58\x01\x58\x02" + b"\x82\x01\x01r"  # req 是字段 16
    back = AllTypes.decode(data)
    assert back.nums == [1, 2]


def test_empty_message(person_mod):
    Address = person_mod.Address
    # 空 message 作为嵌套字段：长度前缀为 0
    Person = person_mod.Person
    msg = Person(name="x", addr=Address(city=""))
    data = msg.encode()
    back = Person.decode(data)
    assert back.addr.city == ""


def test_empty_string_and_bytes(alltypes_mod):
    AllTypes = alltypes_mod.AllTypes
    msg = AllTypes(req="", text="", blob=b"")
    data = msg.encode()
    back = AllTypes.decode(data)
    assert back.text == ""
    assert back.blob == b""
    # 显式赋值的空字符串要编码（tag + len 0）
    assert b"\x42\x00" in data  # 字段 8, len 0


def test_nested_message_wireformat(person_mod):
    # Person.addr 是字段 4：tag = 4<<3|2 = 0x22，内容是 Address 的编码
    Person, Address = person_mod.Person, person_mod.Address
    inner = Address(city="ab").encode()
    data = Person(name="x", addr=Address(city="ab")).encode()
    assert b"\x22" + bytes([len(inner)]) + inner in data


def test_field_ordering_by_number(person_mod):
    # 编码按字段编号升序，与赋值顺序无关
    Person, Address = person_mod.Person, person_mod.Address
    a = Person(name="x", age=1)
    b = Person(age=1, name="x")
    assert a.encode() == b.encode()


def test_int_range_check(alltypes_mod):
    AllTypes = alltypes_mod.AllTypes
    with pytest.raises(EncodeError, match="越界"):
        AllTypes(req="r", i32=2 ** 31).encode()
    with pytest.raises(EncodeError, match="越界"):
        AllTypes(req="r", u32=-1).encode()
    with pytest.raises(EncodeError, match="越界"):
        AllTypes(req="r", u64=2 ** 64).encode()


def test_repr_and_eq(person_mod):
    Person = person_mod.Person
    msg = Person(name="张三", age=30)
    assert "张三" in repr(msg)
    assert msg == Person(name="张三", age=30)
    assert msg != Person(name="张三", age=31)
