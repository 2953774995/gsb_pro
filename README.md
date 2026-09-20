# minipb

一个迷你版 Protocol Buffers：写 schema 文件 → 编译出 Python 类 → 实例编码成紧凑二进制 → 再解码回来。只依赖 Python 标准库（测试用 pytest）。

## 快速开始

```bash
# 编译 schema（也可以 pip install . 之后直接用 `minipb` 命令）
python -m minipb compile person.mpb -o person_pb.py
```

```python
from person_pb import Person, Address

msg = Person(name="张三", age=30,
             emails=["a@b.com"],
             addr=Address(city="北京", zip=100000))
data = msg.encode()            # -> bytes
back = Person.decode(data)     # -> Person，back == msg
```

## schema 语法（.mpb 文件）

```protobuf
// 行注释用 //
message Person {
  required string name = 1;     // 必须赋值，否则编码报错
  optional int32 age = 2;       // 可不赋值，不赋值就不编码
  repeated string emails = 3;   // 列表，可为空
  optional Address addr = 4;    // 嵌套 message
}

message Address {
  required string city = 1;
  optional int32 zip = 2;
}
```

- 修饰符：`required` / `optional` / `repeated`
- 标量类型：`int32`、`int64`、`uint32`、`uint64`、`sint32`、`sint64`、`bool`、`string`、`bytes`、`double`
- 字段类型也可以是本文件里定义的其他 message（支持前向引用）
- 字段编号范围 **1~2047**，同一 message 内不能重复，重复会报带行号的错误
- 解析错误（重复编号、未知类型、缺分号、编号越界……）都会抛 `minipb.SchemaError`，消息里带行号

## 生成的代码

选择**代码生成 .py 文件**而不是运行时动态构造，理由：

1. 生成的代码是普通 Python 文件，可读、可 diff、可进版本库，IDE 能跳转和补全；
2. 运行时只依赖 `minipb.runtime`，部署时不需要 .mpb 文件和解析器；
3. 出错时 traceback 落在真实文件行上，好调试。

生成的类继承 `minipb.runtime.Message`，通过类属性 `_fields` 描述字段，编解码逻辑全部在运行时库里，生成代码本身不含逻辑。

## API

| 操作 | 说明 |
|---|---|
| `Person(name="张三", age=30)` | 构造；optional 未赋值则为 `None`，repeated 默认为 `[]` |
| `msg.encode()` | 编码为 `bytes`；required 未赋值抛 `EncodeError` |
| `Person.decode(data)` | 解码；输入损坏抛 `DecodeError`（带字节偏移） |
| `msg1 == msg2` | 按字段比较 |

## wire format 规则

与 protobuf 的 wire format 一致：

### varint

- 每字节存 7 位数据，最高位（MSB）是续位标志：1 表示后面还有字节
- 小端序：低 7 位在前
- 例：`300` → `0xAC 0x02`；`1` → `0x01`
- 最多 10 字节（64 位）；**int32/int64 的负数按 64 位补码编码，固定占 10 字节**
- 超过 10 字节或超出 64 位 → `DecodeError`

### zigzag（sint32 / sint64）

把有符号数映射成无符号数，让小的负数也有小的编码：

```
encode(n) = (n << 1) ^ (n >> 63)   # 64 位；32 位同理
0 -> 0, -1 -> 1, 1 -> 2, -2 -> 3, ...
```

### tag 与 wire type

每个字段编码为 `tag + value`，其中：

```
tag = (field_number << 3) | wire_type    # 编码为 varint
```

| wire type | 含义 | 用于 |
|---|---|---|
| 0 | varint | int32/int64/uint32/uint64/sint32/sint64/bool |
| 1 | 64-bit | double（小端 IEEE 754） |
| 2 | length-delimited | string/bytes/嵌套 message/packed repeated |
| 5 | 32-bit | （本 schema 无对应字段类型，仅用于跳过未知字段） |

### length-delimited

`string`、`bytes`、嵌套 message 编码为 `varint(长度) + 原始字节`。string 用 UTF-8。

### repeated

- 数值类型（varint 系 + double）用 **packed** 编码：一个 tag（wire type 2）+ 总长度 + 所有元素裸值拼接
- string / message 逐字段编码：每个元素各带一个 tag
- 解码端两种形式都接受（packed 与非 packed 可互相解码）
- 空列表不编码任何字节

### optional / required

- optional 字段未赋值（`None`）时不产生任何字节
- required 字段未赋值时 `encode()` 抛 `EncodeError`；解码时数据里缺 required 字段抛 `DecodeError`

## 向前兼容：未知字段跳过

解码时遇到 schema 里没有的字段编号，按 wire type 跳过对应字节数，不会崩。这样新版写入的数据里多出来的字段，旧版代码照样能读。未知字段被丢弃，重新编码后不再保留。

## 错误处理

所有解码错误抛 `minipb.DecodeError`，消息中带字节偏移（`offset` 属性）：

- varint 超过 10 字节 / 超出 64 位 / 被截断
- 长度前缀超过剩余输入
- 非法 wire type（3、4、6、7）或字段编号 0
- string 字段 UTF-8 解码失败
- 缺 required 字段

编码错误抛 `minipb.EncodeError`（`ValueError` 子类）：required 未赋值、数值越界、类型不匹配。

## 项目结构

```
minipb/
  wire.py     # varint / zigzag / tag / 跳过未知字段
  runtime.py  # Message 基类 + 各类型编解码器（生成代码的运行时依赖）
  schema.py   # .mpb 解析器（手写，带行号报错）
  codegen.py  # 生成 .py 代码
  cli.py      # minipb compile schema.mpb -o out.py
  errors.py   # DecodeError / EncodeError / SchemaError
tests/        # pytest 测试
```

## 运行测试

```bash
python -m pytest tests -q
```

注意：minipb 与真实 protobuf 不保证互通（字段编号范围、required 语义等有简化），但 wire format 规则严格遵守，自己跟自己 roundtrip 字节级稳定。
