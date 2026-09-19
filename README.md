# minimq

一个从零实现的迷你内存消息队列（mini message queue），**仅使用 Python 标准库**
（测试框架 pytest 除外）。支持主题发布/订阅、消费组负载均衡、消费者确认、
磁盘持久化、保留策略与并发安全访问。

## 功能概览

- **主题（Topic）发布订阅**：`publish` 追加消息，offset 从 0 开始单调递增
- **消费组（Consumer Group）**：Polling 模型；同组多消费者负载均衡、互不重复；
  不同消费组各自独立消费全量消息
- **确认与重投递**：`ack(offset)` 确认；未确认消息在重新 poll、消费者重连或
  broker 重启后会被重新投递（at-least-once）
- **持久化**：消息追加写入带长度前缀 + CRC32 校验的日志文件；消费组已确认
  偏移量持久化；损坏的尾部记录（半条消息）在恢复时被安全截断
- **保留策略**：按最大消息数（`max_messages`）或最大字节数（`max_bytes`）
  从旧到新丢弃，并同步压缩磁盘日志
- **并发安全**：多生产者、多消费者并发访问由内部锁保护
- **错误处理**：所有误用抛出统一的 `MqError`，带明确信息

## 数据模型

```
Broker
 └── Topic "t"            # 有序消息序列，offset 单调递增（从 0 开始）
 │    ├── base_offset     # 当前最老可用 offset（保留策略会推进它）
 │    └── next_offset     # 下一条消息的 offset（永不回退）
 └── ConsumerGroup (topic, group)
      ├── committed       # 已确认的连续水位线（持久化）
      ├── next_fetch      # 下一条待分发的 offset
      ├── inflight        # 已投递未确认: offset -> consumer_id
      └── pending         # 消费者断开后释放、待重投递的 offset 堆
```

**消费语义**：

- 组内：每条消息只投递给组内一个消费者（负载均衡）；消费者 `close()`
  （断开）后，其未确认消息回到 pending 池，由组内其他消费者重新拉取
- 组间：每个消费组独立维护自己的 offset，各自消费全量消息
- 重投递：消费者再次 `poll` 时优先收到自己未确认的消息；`ack` 一个未投递
  或已确认的 offset 会抛 `MqError`
- 保留策略丢弃消息后，滞后的消费者 offset 会被钳制到 `base_offset`，
  语义保持正确

## 持久化格式

数据目录布局：

```
data_dir/
├── topics/
│   └── <topic>/
│       ├── messages.log   # 消息日志（追加写）
│       └── meta.json      # 主题元数据（保留策略配置）
└── groups/
    └── <topic>__<group>.json   # 消费组已确认水位线 {"committed": N}
```

`messages.log` 记录格式（大端序）：

```
+-------------------+-------------------+======================+
| length (4 字节)   | crc32 (4 字节)    | payload (length 字节)|
+-------------------+-------------------+======================+
```

- payload 为 UTF-8 JSON：`{"offset": int, "body": str}`
- CRC32 只对 payload 计算
- 恢复时顺序读取，遇到不完整记录（写了一半）或 CRC 校验失败即停止，
  并将文件**截断到最后一条完好记录**，崩溃安全
- 保留策略触发时重写整个日志文件（compaction，临时文件 + 原子 rename）
- 组偏移量文件同样采用临时文件 + 原子 rename 写入

## 快速开始

要求：Python 3.8+，无第三方依赖。

### Python API

```python
from minimq import Broker, MqError

broker = Broker(data_dir="./mq-data")   # 不传 data_dir 则纯内存
broker.create_topic("events", max_messages=1000)

offset = broker.publish("events", "hello")     # -> 0

consumer = broker.subscribe("events", "my-group")
messages = consumer.poll(max_messages=10)      # 拉取
for msg in messages:
    print(msg.offset, msg.body)
    consumer.ack(msg.offset)                   # 确认

consumer.close()
broker.close()

# 重启后消息与已确认 offset 都会恢复
broker2 = Broker(data_dir="./mq-data")
```

### 命令行工具 minimq-cli

安装后可直接使用 `minimq-cli`（也可以用 `python3 -m minimq` 代替）：

```bash
pip install .            # 安装包与 minimq-cli 命令（可选）

# 创建主题（带保留策略）
python3 -m minimq --data-dir ./mq-data create events --max-messages 1000

# 发布一条消息
python3 -m minimq --data-dir ./mq-data produce events "hello world"

# 消费（拉取并打印，自动 ack；--no-ack 可验证重投递）
python3 -m minimq --data-dir ./mq-data consume events -g my-group -n 10

# 列出主题与偏移量
python3 -m minimq --data-dir ./mq-data topics
```

所有状态都保存在 `--data-dir` 指定的目录中（默认 `./minimq-data`，
也可用环境变量 `MINIMQ_DATA_DIR` 指定）。

## 代码结构

```
minimq/
├── __init__.py    # 对外导出 Broker / Consumer / Message / MqError
├── errors.py      # MqError 自定义异常
├── storage.py     # RecordLog：长度前缀 + CRC32 的追加日志，损坏尾部截断
├── topic.py       # Topic：消息序列、offset 管理、保留策略
├── group.py       # ConsumerGroup：分发、in-flight 跟踪、ack 水位线持久化
├── broker.py      # Broker：主题/消费组管理、并发锁、恢复；Consumer API
├── cli.py         # minimq-cli 命令行入口
└── __main__.py    # python3 -m minimq
tests/             # pytest 测试套件（46 个用例）
```

## 运行测试

```bash
python3 -m pytest tests/ -v
```

测试全部在临时目录中运行，覆盖：发布/拉取/确认基本流程、组内负载均衡
不重复、多消费组独立消费、未确认消息重投递（重新 poll / 重连 / 重启）、
offset 单调递增、重启恢复消息与已确认 offset、损坏尾部截断、保留策略、
多生产者多消费者并发、各类错误场景以及 CLI 端到端流程。
