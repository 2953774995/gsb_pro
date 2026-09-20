# minibroker

`minibroker` 是一个从零实现的迷你发布/订阅消息队列。它提供多线程 TCP 服务端、标准库 Python 客户端 SDK 和交互式 `mb-cli`，运行与测试只使用 Python 标准库（测试使用 `pytest`）。

## 特性

- 自定义、明确的长度前缀文本协议，可承载任意二进制 payload。
- TCP 服务默认监听 `127.0.0.1:7379`，可用 `--port` 修改。
- 命令：`PUBLISH`、`SUBSCRIBE`、`UNSUBSCRIBE`、`PING`、`STATS`、`FLUSH`、`SHUTDOWN`。
- 同一连接可订阅多个 topic。
- 支持前缀层级通配：`news/*` 匹配 `news/tech`、`news/sports/game`；`*` 匹配全部 topic。
- 全局单调递增、稠密的消息序号。
- 每个 topic FIFO；多个订阅者独立 fan-out，不共享 offset。
- 无订阅者时按 topic 保留最近 N 条（默认 1000），N=0 时立即丢弃。
- 所有成功的 `PUBLISH` 顺序追加到 AOF；重启回放消息和序号。
- 多线程网络模型，核心状态由锁保护；慢客户端不会阻塞发布者或其他连接。
- 畸形请求返回标准 `ERR`，连接被关闭，服务器继续服务。
- `SHUTDOWN` 先回复执行命令的客户端，再异步通知所有连接并优雅退出。

## 目录结构

```text
minibroker/
  __init__.py       # 公共 API
  protocol.py       # 协议解析器、序列化器、回复解析
  messages.py       # 消息数据类型
  topics.py         # topic 校验与通配匹配
  persistence.py    # AOF 写入、回放、截断、文件锁
  broker.py         # 线程安全的内存队列、保留策略、订阅表、fan-out
  server.py         # TCP 服务端、连接线程、命令处理
  client.py         # BrokerClient Python SDK
  cli.py            # mb-cli 交互逻辑
mb-cli              # CLI 可执行入口
tests/              # pytest 测试
```

## 快速开始

要求 Python 3.8+（仅使用标准库）。

### 启动 broker

```bash
python3 -m minibroker
# 或指定端口/AOF/保留策略
python3 -m minibroker --host 127.0.0.1 --port 7379 \
  --aof .broker.aof \
  --retention 1000
```

常用参数：

- `--port`：监听端口，默认 `7379`。
- `--host`：监听地址，默认 `127.0.0.1`。
- `--aof`：AOF 文件路径，默认 `.broker.aof`。
- `--no-aof`：禁用持久化，仅用于临时演示/测试。
- `--retention N`：无订阅者时每个 topic 在内存中保留最近 N 条；`0` 表示丢弃。
- `--max-client-queue N`：限制每个连接待推送队列长度；默认 `0` 表示不限。
- `--max-command-size N`：单条命令 wire frame 字节上限，默认 1048576（1 MiB）。

### 使用 Python SDK

```python
from minibroker import BrokerClient

subscriber = BrokerClient(port=7379).connect()
subscriber.subscribe("news/tech")

publisher = BrokerClient(port=7379).connect()
sequence = publisher.publish("news/tech", b"hello world")
message = subscriber.next_message(timeout=5)
print(message.sequence, message.topic, message.payload)

publisher.close()
subscriber.close()
```

`BrokerClient` 方法：

- `connect()` / `close()`，也支持 context manager。
- `ping()`
- `publish(topic, payload) -> int`：返回全局消息序号。
- `subscribe(topic)`
- `unsubscribe(topic) -> bool`
- `next_message(timeout=None) -> Message`：阻塞等待，超时抛 `TimeoutError`。
- `stats()` / `flush()` / `shutdown()`

`topic` 和 `payload` 可以传 `bytes` 或 `str`；要发送任意字节（NUL、CR/LF 等）请使用 `bytes`。

### 使用 CLI

```bash
./mb-cli --port 7379
# 或
python3 -m minibroker.cli --port 7379
```

交互示例：

```text
mb> ping
PONG
mb> subscribe news/tech
SUBSCRIBED news/tech; waiting (Ctrl-C to stop)
```

另一个 CLI 或 SDK 发布后，订阅窗口实时打印：

```text
[PUB #7] news/tech: hello
```

在订阅模式按 `Ctrl-C` 可回到命令行。还支持 `publish`、`unsubscribe`、`stats`、`flush`、`shutdown`、`help`、`quit`。CLI 使用 shell-like quoting，因此引号中的空格和制表符可作为一个参数；完整二进制载荷请使用 Python SDK。

## 线协议定义

协议是类似 RESP2 数组/长度前缀字符串的小型文本协议。命令和异步 PUB 都使用数组 frame：

```text
*<参数数量>\r\n
$<该参数字节长度>\r\n
<精确字节数>\r\n
...
```

例如 `PUBLISH topic abc`：

```text
*3\r\n
$7\r\n
PUBLISH\r\n
$5\r\n
topic\r\n
$3\r\n
abc\r\n
```

因为每个参数都按明确字节数读取，payload 可包含空格、制表符、NUL、CR、LF 和任意二进制数据。

### 回复类型

```text
+PONG\r\n                    # 简单成功回复
:123\r\n                     # 整数回复，PUBLISH 返回消息序号
-ERR bad topic\r\n           # 标准错误回复
*3\r\n$5\r\nSTATS\r\n...     # 数组回复
```

异步推送：

```text
*4\r\n
$3\r\n
PUB\r\n
$1\r\n
7\r\n
$5\r\n
topic\r\n
$3\r\n
abc\r\n
```

服务器关闭时推送：

```text
*1\r\n$8\r\nSHUTDOWN\r\n
```

解析器按 frame 的所有字节（头部、长度、载荷和 CRLF）计算大小。默认单帧超过 1 MiB 返回 `ERR protocol error: frame exceeds maximum size` 并关闭该连接。

## 命令语义

| 命令 | 参数 | 成功回复 | 说明 |
|---|---|---|---|
| `PING` | 无 | `+PONG` | 健康检查 |
| `PUBLISH` | `topic payload` | `:<sequence>` | 写 AOF、保留、fan-out |
| `SUBSCRIBE` | `topic` | `+SUBSCRIBED` | 可重复订阅多个 topic，订阅时回放仍在保留窗口中的消息 |
| `UNSUBSCRIBE` | `topic` | `+UNSUBSCRIBED` / `+NOT_SUBSCRIBED` | 取消订阅并移除该订阅在本连接中尚未消费的推送 |
| `STATS` | 无 | 数组 | 连接、订阅、保留消息、下一个序号等状态 |
| `FLUSH` | 无 | `+FLUSHED` | 清空内存、连接待推送、AOF 文件，并重置序号 |
| `SHUTDOWN` | 无 | `+BYE` | 触发优雅关闭 |

### Topic 与通配规则

- topic 不能为空，不能包含 ASCII 控制字符（包括换行、制表、NUL、DEL）。
- 普通 topic 不允许包含 `*`。
- `prefix/*` 表示层级前缀，必须至少匹配 `/` 后的一个非空 path segment。
- `*` 匹配所有 topic。
- 示例：`news/*` 匹配 `news/tech`、`news/sports/game`，不匹配根 topic `news`。

## 队列、保留和容量策略

- 内存路由状态由一个全局 `RLock` 保护。序号分配、AOF 追加、保留和 fan-out 相对于其他命令是原子顺序。
- 每个连接有独立的待发送 FIFO 队列和独立 writer 线程。
- 同一连接同时命中精确订阅、`prefix/*` 和 `*` 时，一条消息只投递一次。
- 默认 `--max-client-queue 0`：连接待发送队列不设限，慢/阻塞客户端不丢消息，但会消耗内存。
- 设置为正整数 N 时：如果任一目标连接的待发送队列已满，`PUBLISH` 返回错误 `ERR client queue full (...)`，该发布不分配序号、不写 AOF，也不会产生部分投递。当前实现选择显式背压/拒绝，不做无限阻塞，避免一个挂住的客户端阻塞发布线程。
- 无订阅者消息按 topic 保留最近 N 条。新订阅者会先收到仍在窗口内的历史消息，再收到实时消息。
- 连接异常断开时，它自己的待发送队列被丢弃，订阅关系从路由表删除；其他订阅者和 AOF 不受影响。

## 持久化与恢复

默认 AOF 文件为当前工作目录下的 `.broker.aof`。每条成功消息写一条：

```text
["MSG", "<decimal-sequence>", topic, payload]
```

磁盘记录使用与网络相同的长度前缀 frame。写入顺序与命令执行顺序一致；每次追加都会 flush/fsync。重启时：

1. 获取 AOF 排它咨询文件锁，防止两个 broker 使用同一文件。
2. 顺序回放所有完整记录。
3. 根据 `--retention` 重建每个 topic 的内存保留窗口。
4. 将下一个序号设置为最大序号 + 1，保证后续 PUBLISH 连续。
5. 若末尾是进程崩溃造成的半条记录，截断该不完整尾部；中间记录损坏会拒绝启动而不是静默忽略。
6. `FLUSH` 清空并 fsync AOF，同时将序号重置为 1。

## 并发模型

- 一个 accept 线程接收连接。
- 每个连接两个线程：
  - reader：解析 frame、执行命令；
  - writer：按 FIFO 将 PUB frame 写入 socket。
- `Broker` 的订阅表、保留 deque、计数器和连接注册表由锁保护。
- 网络写操作不放在 broker 全局锁内；fan-out 只是把消息放入连接队列并唤醒 writer。

## 测试

```bash
python3 -m pytest tests/ -v
```

覆盖内容包括：

- 空载荷、空格、制表符、CR/LF、NUL 和任意字节往返。
- 1 MiB 超长命令、缺少长度、负数长度、缺 CRLF、非法数组等协议边界。
- 订阅前/订阅后发布。
- 多个订阅者 fan-out、取消订阅和异常断开互不影响。
- 保留最近 N、N=0 丢弃、重启重建窗口。
- 全局序号单调稠密；FLUSH 后重置。
- AOF 写入、重启恢复、序号连续性、尾部截断、中间损坏、AOF 文件锁。
- 10 个订阅者 + 3 个发布线程的并发发布，校验无丢失无重复。
- 通配订阅和重叠通配去重。
- 未知命令、错误参数、非法 topic、协议错误。
- `SHUTDOWN` 通知和优雅退出。

## 手动验收示例

终端 1：

```bash
python3 -m minibroker --port 7379
```

终端 2：

```bash
./mb-cli --port 7379
mb> subscribe demo
```

终端 3：

```bash
./mb-cli --port 7379
mb> publish demo hello
mb> publish demo world
mb> shutdown
```

终端 2 应依次收到序号递增的两条消息。要验证 AOF：

```bash
python3 -m minibroker --port 7379 --aof .broker.aof
# publish demo persisted
# Ctrl-C 或 SHUTDOWN 后重启
python3 -m minibroker --port 7379 --aof .broker.aof
# 新客户端 subscribe demo，可收到仍处于保留窗口中的历史消息
```
