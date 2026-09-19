# minimq

一个**迷你内存消息队列**：支持主题（Topic）发布/订阅、消费组（Consumer Group）
拉取消费、消费者确认（ack）、磁盘持久化与重启恢复、保留策略清理。

* 仅使用 **Python 3 标准库**，运行时代码零第三方依赖（测试仅需 `pytest`）。
* 消息保存在内存中以提供快速 poll，同时以**只追加日志（append-only log）**
  持久化到磁盘；broker 重启后可完整恢复消息、偏移量与消费组确认进度。

---

## 1. 快速开始

```bash
# 运行测试（无需安装任何东西）
python3 -m pytest tests/ -v

# 使用命令行（状态保存在 data 目录）
python3 -m minimq --data-dir ./data create-topic orders
python3 -m minimq --data-dir ./data produce orders "hello"
python3 -m minimq --data-dir ./data consume orders --group web --max 10 --ack
python3 -m minimq --data-dir ./data topics
python3 -m minimq --data-dir ./data groups
```

仓库根目录还附带一个可直接执行的等价启动器：`./minimq-cli --data-dir ./data ...`。

### Python API

```python
from minimq import Broker, MqError

with Broker(data_dir="./data") as broker:
    broker.create_topic("orders", max_messages=10_000)

    # 生产者
    offset = broker.publish("orders", b"hello")      # bytes 或 str
    print(offset)                                    # 0, 1, 2, ...

    # 消费者（同一 group 负载均衡；不同 group 各自消费全量）
    c = broker.subscribe("orders", "payment-service")
    batch = c.poll(max_messages=100)
    for msg in batch:
        print(msg.offset, msg.value)
        c.ack(msg.offset)          # 或 c.consume(msg.offset)
```

---

## 2. 数据模型

```
Broker
 └── Topic（一个分区 / 一条 append-only 日志）
      ├── Message(offset: int, value: bytes)   offset 从 0 开始单调递增
      └── ConsumerGroup(group 名字)
           ├── 已确认进度：hwm（高水位）+ gaps（hwm 之上乱序 ack 的空洞）
           ├── inflight 表：offset -> consumer_id（已投递未确认）
           └── Consumer（轮询句柄，多个 Consumer 共享同一 group 状态）
```

* **发布**：`publish(topic, message)` 将消息追加到 topic 日志，返回单调递增 offset。
* **订阅与拉取**：`subscribe(topic, group)` 返回 `Consumer`；`poll(max_messages)`
  从 group 共享的"可投递 offset 集合"中拉取消息（**Polling 模型，无回调**）。
  已投递给同组某个消费者但未 ack 的消息，不会投递给同组其他消费者。
* **确认**：`ack(offset)`（`consume(offset)` 是其别名）确认消息并持久化进度。
* **重新投递**：未 ack 的消息在以下情况会被重新投递：
  * 持有该消息的 consumer `close()`（模拟崩溃/重连），其 inflight 租约释放，
    同组其他（或新的）consumer 再次 `poll` 即可拿到；
  * broker 重启后：inflight 是内存态，未确认消息重新变为可投递。
* **消费组语义**：
  * 同组多个 consumer **不重复消费**同一条消息（负载均衡）；
  * 不同 group **独立维护确认进度**，每个 group 都能看到 topic 的全量消息；
  * 新 group 从 topic 当前保留窗口的最早 offset 开始消费。

### 乱序确认：hwm + gaps

为了正确支持"先 ack 后面的、再 ack 前面的"，group 进度持久化为：

* `hwm`：所有 `< hwm` 的 offset 都已确认（连续确认高水位）；
* `gaps`：`>= hwm` 但已经确认的 offset 集合。

ack 时若 offset == hwm，则推进 hwm 并连续"吃掉" gaps 中后续已确认点。
poll 时跳过 `< hwm`、在 gaps 中、以及在 inflight 中的 offset。

---

## 3. 持久化格式

数据目录布局：

```
data/
 ├── topics.json              # topic 配置（保留策略、消息大小上限）
 ├── logs/
 │    └── <topic>.log         # 每个 topic 一条只追加消息日志
 └── groups/
      └── <topic>!<group>.json  # 每个 (topic, group) 一份确认进度
```

topic/group 名字做了百分号编码（`%XX`，`!` 是编码后不会出现的分隔符），
所以任意合法名字都能安全映射成文件名且可无歧义解析。

### 3.1 消息日志记录格式（自定义二进制帧）

每条记录采用"长度前缀 + 校验和"，整数全部使用大端序：

```
+--------+------------+-------------+---------+--------+
| magic  | length     | offset      | payload | crc32  |
| 1 byte | 4 bytes    | 8 bytes     | N bytes | 4 bytes|
| 0x4D   | uint32     | uint64      |         | uint32 |
+--------+------------+-------------+---------+--------+
```

* `magic` 固定 `0x4D`（"M"），用于识别帧；
* `length` 是 payload 字节数；`offset` 是消息偏移量；
* `crc32 = zlib.crc32(magic + length + offset + payload)`（标准库 `zlib`）。

写入时每条记录 `flush + fsync`（可用 `Broker(..., fsync=False)` 关闭用于压测）。

### 3.2 恢复与损坏尾部截断

启动时顺序扫描日志，逐条校验 magic、长度与 crc32：

* 完整且校验通过的记录全部恢复；
* **半条消息 / 损坏尾部**（写了一半的 header、被截断的 payload、错误的
  crc32、未知 magic）会立即停止扫描，并把文件**安全截断到最后一个有效字节**，
  broker 不会崩溃，后续写入仍保持帧对齐。

### 3.3 消费组进度文件（JSON，原子替换）

```json
{"hwm": 5, "gaps": [7, 9]}
```

每次 ack 写入同目录临时文件、`fsync` 后 `os.replace` 原子改名，
因此重启后已确认的消息不会被重复消费。

### 3.4 保留策略与日志压缩

* `max_messages`：最多保留 N 条消息；
* `max_bytes`：最多保留 N 字节 payload；
* 两者可同时配置，超出时从最旧（offset 最小）开始丢弃，直到不超限。

丢弃内存窗口中的旧消息后，会用有效消息**重写日志文件**（临时文件 +
`os.replace` 原子替换），保证磁盘文件也不会无限增长。被丢弃的 offset
会同步推进各消费组的 hwm / 清理 inflight，因此消费者不会再收到这些消息，
offset 语义保持正确。

---

## 4. 并发安全

* `Broker` 内部持有一把 `threading.RLock`，所有公开操作（创建 topic、
  publish、subscribe、poll、ack、保留清理）都在锁内执行；
* poll 的"挑选可投递 offset + 标记 inflight"与 ack 的"校验归属 + 更新进度 +
  持久化"都是临界区内的原子操作，多生产者/多消费者并发下不会出现数据竞争、
  消息丢失或同组重复投递（见 `tests/test_concurrency.py`）。

---

## 5. 错误处理（`minimq.errors.MqError`）

所有可预期错误都抛出 `MqError` 子类，信息明确：

| 场景 | 异常 |
| --- | --- |
| 对不存在的 topic publish / subscribe | `TopicNotFoundError` |
| 重复创建同名 topic | `TopicExistsError` |
| 重复 ack 同一 offset | `ConsumerGroupError`（信息含 "duplicate ack"） |
| ack 未投递给自己的 offset / 未 poll 就 ack | `ConsumerGroupError` |
| ack 不存在 / 已被保留策略丢弃的 offset | `MqError` / `ConsumerGroupError` |
| 发布超过 `max_message_size` 的消息 | `MessageTooLargeError` |
| 非法 topic/group 名字、非法 poll 参数 | `MqError` |

CLI 遇到 `MqError` 时打印 `error: ...` 并以退出码 `2` 结束。

---

## 6. CLI 参考

```
python3 -m minimq --data-dir DIR [--no-fsync] <command> [options]

create-topic TOPIC [--max-messages N] [--max-bytes N] [--max-message-size N]
delete-topic TOPIC
topics                       # 列出 topic 及 begin/end/next offset、消息数、字节数
groups [--topic TOPIC]       # 列出消费组及 hwm/gaps
produce TOPIC [MESSAGE]      # MESSAGE 省略时从 stdin 读取；打印新 offset
consume TOPIC --group G [--max N] [--ack] [--wait SECONDS]
                             # 按 "offset<TAB>消息内容" 逐行打印；--ack 边消费边确认
```

每次 CLI 调用都是一次独立的"broker 进程"：从 `--data-dir` 恢复、执行操作、
退出。因此连续调用 consume 即可验证"重连后未确认消息重新投递、已确认不重复"。

---

## 7. 代码组织

| 模块 | 职责 |
| --- | --- |
| `minimq/broker.py` | Broker：topic/group 管理、元数据、加锁、生命周期 |
| `minimq/topic.py` | Topic：内存消息窗口、发布、保留清理、日志接入 |
| `minimq/storage.py` | `LogStorage`：二进制追加日志、恢复校验、损坏截断、原子重写 |
| `minimq/consumer.py` | `ConsumerGroup` / `Consumer` / `Message`、hwm+gaps 进度持久化 |
| `minimq/retention.py` | `RetentionPolicy`：max_messages / max_bytes 保留策略 |
| `minimq/errors.py` | `MqError` 异常体系 |
| `minimq/cli.py`、`minimq/__main__.py` | `minimq-cli` 命令行 |
| `minimq-cli` | 免安装的根目录启动脚本 |
| `tests/` | pytest 测试（55 个用例，全部在临时目录运行） |

### 测试覆盖

* 基本 publish → poll → ack 流程、offset 从 0 单调递增、乱序 ack 空洞；
* 同组多消费者负载均衡不重复；不同消费组各自独立消费全量；新组从头开始；
* 未确认消息在消费者关闭/重连、broker 重启后的重新投递；
* 重启恢复消息与 offset；已确认 offset 重启后不重复；gaps 持久化；
* 损坏尾部（半截 header、半截 payload、crc32 错误、magic 错误）安全截断；
* `max_messages` / `max_bytes` 保留策略丢旧消息、重启后仍正确、日志压缩；
* 并发多生产者 / 多消费者 / 同时生产消费，无丢失无重复；
* 全部错误场景抛出 `MqError`；
* CLI 端到端流程（基于子进程，真实磁盘目录）。

运行：

```bash
python3 -m pytest tests/ -v
```
