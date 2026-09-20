# minipb — 迷你版 Protocol Buffers

只用 Python 标准库（测试用 pytest）实现的迷你 protobuf：

- 手写 `.mpb` schema 文件
- `minipb compile` 编译成普通 Python 模块
- 实例 `encode()` 成紧凑二进制，`decode()` 还原
- wire format 规则与 Protocol Buffers 一致（varint / zigzag / packed / 未知字段跳过）

## 快速开始

```bash
# 编译 schema（也可以用 python -m minipb）
minipb compile examples/person.mpb -o examples/person_pb.py
```

```python
import person_pb

msg = person_pb.Person(
    name="张三", age=30,
    emails=["a@x.com"],
    addr=person_pb.Address(city="上海", zip=200000),
)
data = msg.encode()                      # -> bytes
back = person_pb.Person.decode(data)     # -> Person
assert back == msg
```

运行测试：

```bash
python -m pytest tests/
```

## Schema 语法（.mpb）

```proto
// 支持 // 行注释和 /* */ 块注释
message Person {
  required string name = 1;     // 必须赋值，否则 encode 报 EncodeError
  optional int32 age = 2;       // 不赋值就不编码
  repeated string emails = 3;   // 可重复字段
  optional Address addr = 4;    // 嵌套 message 类型
}

message Address {
  required string city = 1;
  optional int32 zip = 2;
}
```

规则：

- 每个字段：`required|optional|repeated 类型 名字 = 编号;`
- 字段编号范围 **1 ~ 2047**，同一 message 内编号和字段名都不能重复，重复报带行号的 `SchemaError`
- 内置类型：`int32` `int64` `uint32` `uint64` `sint32` `sint64` `bool` `string` `bytes` `double`
- 字段类型也可以是本文件里定义的其他 message（允许前向引用）；未知类型报错
- 解析器是手写的递归下降（`minipb/schema.py`），所有语法错误都带行号

## Wire format 规则

与 Protocol Buffers 一致：

### varint

- 7 位一组，每组最高位是续位标志（1 = 还有下一组），小端序（低位组在前）
- 最多 10 字节（64 位）；解码时超过 10 字节抛 `DecodeError`
- 例：`300` → `0xAC 0x02`；`2**64-1` → `0xFF×9 + 0x01`

### zigzag（sint32 / sint64）

把有符号数映射成无符号数，让小的负数也用短 varint：

```
0 -> 0, -1 -> 1, 1 -> 2, -2 -> 3, ...
encode: (n << 1) ^ (n >> 63)   （sint32 用 >> 31）
```

### 字段编码

每个字段 = **tag + value**：

```
tag = varint(field_number << 3 | wire_type)
```

| wire type | 值 | 用途 |
|-----------|---|------|
| varint | 0 | int32/int64/uint32/uint64/sint32/sint64/bool |
| 64-bit | 1 | double（小端 8 字节） |
| length-delimited | 2 | string/bytes/嵌套 message/packed repeated |
| 32-bit | 5 | （保留，跳过未知字段时支持） |

- **string/bytes/嵌套 message**：`varint(长度) + 内容`，string 必须是合法 UTF-8
- **int32/int64 负数**：按 64 位补码编码成 10 字节 varint（与 protobuf 一致）
- **repeated 数值类型**（int/sint/uint/bool/double）：**packed** 编码 —— 一个 tag（wire type 2）+ 总长度 + 所有值直接拼接
- **repeated string/message**：逐字段编码（每个元素一个 tag）
- 解码端同时兼容 packed 和非 packed 的 repeated 数值字段

### 未知字段跳过（向前兼容）

解码时遇到 schema 里没有的字段编号，按 wire type 跳过对应字节，不报错：

- wire 0：跳过一个 varint
- wire 1：跳过 8 字节
- wire 2：读长度前缀，跳过对应长度
- wire 5：跳过 4 字节
- 其他 wire type：抛 `DecodeError`

## 错误处理

自定义异常（`minipb/errors.py`）：

| 异常 | 场景 |
|------|------|
| `SchemaError` | schema 语法/校验错误，带**行号**（`.line`） |
| `DecodeError` | 二进制解码错误，带**字节偏移**（`.offset`） |
| `EncodeError` | required 未赋值、数值越界、类型不对 |

`DecodeError` 覆盖：varint 超 10 字节、varint 截断、长度前缀超出剩余缓冲区、
非法 wire type（3/4/6/7）、字段编号 0、UTF-8 解码失败、已知字段 wire type 不匹配、
required 字段缺失。嵌套 message 内部的错误会把偏移换算成外层缓冲区偏移。

## API

```python
class Person(Message):
    ...

msg = Person(name="张三", age=30)   # 关键字参数赋值；未知字段名报 TypeError
msg.age = 31                        # 也可以后赋值
data = msg.encode()                 # -> bytes；required 缺失抛 EncodeError
msg2 = Person.decode(data)          # 类方法；数据有问题抛 DecodeError
msg == msg2                         # 按字段值 + 赋值状态比较
```

- `optional` 字段没赋值就不编码（显式赋 0 / 空字符串也会编码，presence 语义）
- `repeated` 字段默认是空列表，直接 `msg.emails.append(...)` 或整体赋值
- 数值字段编码时做范围检查（如 `int32` 必须在 `[-2**31, 2**31-1]`）

## 设计说明：为什么选「生成 .py 文件」

编译器（`minipb/compiler.py`）把 schema 编译成一个**普通的、可读的 Python 模块**，
而不是运行时动态构造类。理由：

1. **可检查**：生成的代码就是一串 `Field(...)` 声明，肉眼可审，diff 友好，适合进版本库
2. **无运行时依赖 schema**：部署时只需要生成的 `.py` + `minipb` 运行时，不需要 .mpb 文件
3. **导入即普通模块**：`import person_pb` 和任何 Python 模块一样，IDE 跳转/补全正常
4. **逻辑集中**：所有编解码逻辑在 `minipb/runtime.py`，生成代码不含逻辑，
   修 bug 只改 runtime，不用重新生成

## 项目结构

```
minipb/
  wire.py       # varint / zigzag / tag / 字段跳过
  runtime.py    # Message 基类 + 标量类型编解码表
  schema.py     # .mpb 手写解析器（递归下降，带行号报错）
  compiler.py   # Schema -> .py 代码生成
  cli.py        # minipb compile schema.mpb -o out.py
  errors.py     # SchemaError / DecodeError / EncodeError
tests/          # pytest：varint、zigzag、roundtrip、未知字段、schema 错误、CLI
examples/       # person.mpb 示例
```

## 安装

```bash
pip install -e .        # 提供 minipb 命令
# 或者不安装，直接用：
python -m minipb compile schema.mpb -o out.py
```
