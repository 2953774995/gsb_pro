# linebus

`linebus` 是一个面向车间质检工位（相机、传感器、MES、电子看板等）的轻量级事件分发服务。服务使用 TCP 长连接，提供发布/订阅、全局有序序号、内存 fan-out、AOF 持久化与重启恢复。运行时代码**只使用 Python 标准库**；测试使用 `pytest`。

## 特性

- 自定义、可读的文本协议，载荷采用长度前缀，可承载任意字节（空格、制表符、换行、NUL、二进制图片片段等）。
- TCP 服务默认监听 `127.0.0.1:7379`，可用 `--host`、`--port` 修改。
- 命令支持：`PUBLISH`、`SUBSCRIBE`、`UNSUBSCRIBE`、`PING`、`STATS`、`FLUSH`、`SHUTDOWN`。
- 一个连接可订阅多个 topic；支持单段通配订阅，例如 `camera/*`。
- 每个订阅连接拥有独立 FIFO 队列，同一事件可 fan-out 到多个连接，互不阻塞和污染。
- 事件带全局单调递增序号；每个订阅方严格按发布顺序接收。
- 无订阅方事件默认按 topic 保留最近 1000 条，晚加入的订阅方可回放；`--retention 0` 表示立即丢弃。
- 慢订阅方队列满时默认返回 `ERR`；也可配置 `--on-full block` 阻塞等待。
- 所有成功的 `PUBLISH` 在响应前追加并 fsync 到 `.linebus.aof`，启动时回放事件与序号。
- 多线程网络模型，topic 日志、订阅表、连接 outbox 均由同一把可重入锁和条件变量保护。
- 单连接异常断开只清理该连接的订阅和待发送队列；其他订阅方继续消费。
- 单条命令默认最大 1 MiB；畸形请求返回 `ERR`，协议边界无法恢复时关闭该连接，服务进程不退出。
- `SHUTDOWN` 先向已连接客户端推送 `BYE`，再关闭监听和连接。

## 目录结构

```text
linebus/
  protocol.py  # 协议解析器、序列化器、错误类型
  storage.py   # Event、topic 校验、通配匹配
  aof.py       # AOF 追加、fsync、启动回放、尾部损坏截断
  broker.py    # 线程安全 topic 日志、订阅表、每连接 FIFO outbox
  server.py    # TCP 服务端与会话线程
  client.py    # LinebusClient SDK
  cli.py       # lb-cli 交互式/命令行客户端
  __main__.py  # python -m linebus 入口
tests/         # pytest 测试
```

## 快速开始

要求 Python 3.9+。

### 启动服务

```bash
python3 -m linebus --host 0.0.0.0 --port 7379 --aof .linebus.aof
```

可选参数：

```bash
python3 -m linebus \
  --host 0.0.0.0 \
  --port 7379 \
  --aof .linebus.aof \
  --retention 1000 \
  --queue-capacity 1000 \
  --on-full reject \
  --max-command-size 1048576
```

- `--retention N`：每个 topic 保留最近 N 条无订阅方时产生的事件；`0` 为丢弃。
- `--queue-capacity N`：每个连接已推送但尚未写入 socket 的最大事件数。
- `--on-full reject`（默认）：慢订阅方队列满时，`PUBLISH` 返回 `ERR ... queue is full`，不写 AOF、不递增序号。
- `--on-full block`：发布线程等待队列空位，保证背压下不丢事件；一个极慢订阅方会阻塞对应发布。
- `--max-command-size N`：单条载荷上限，默认 1048576 字节。

### Python SDK

```python
from linebus import LinebusClient

subscriber = LinebusClient("127.0.0.1", 7379).connect()
subscriber.subscribe("camera/line-1")
subscriber.subscribe("sensor/*")

publisher = LinebusClient("127.0.0.1", 7379).connect()
seq = publisher.publish("camera/line-1", b"defect: scratch\nlevel: high\x00binary")

event = subscriber.next_message(timeout=5)
print(event.sequence, event.topic, event.payload)
assert event.sequence == seq

publisher.close()
subscriber.close()
```

`LinebusClient` 支持 `connect()`、`close()`、上下文管理器，以及：

- `publish(topic, payload)`：返回全局序号。
- `subscribe(topic)` / `unsubscribe(topic)`。
- `next_message(timeout=None)`：阻塞等待服务端事件；超时抛 `LinebusTimeout`。
- `ping()`、`stats()`、`flush()`、`shutdown()`。

### lb-cli

仓库根目录提供包装脚本：

```bash
./lb-cli --host 127.0.0.1 --port 7379
```

也可直接运行：

```bash
python3 -m linebus.cli
```

交互命令：

```text
lb> ping
lb> publish camera/1 photo-ok
lb> subscribe camera/1 sensor/*
lb> unsubscribe camera/1
lb> stats
lb> flush
lb> quit
```

订阅后，CLI 后台线程会实时打印：

```text
EVENT 42 camera/1 8 b'photo-ok'
```

一次性命令：

```bash
python3 -m linebus.cli publish camera/1 photo-ok
python3 -m linebus.cli subscribe camera/1 sensor/*
python3 -m linebus.cli stats
```

## 线协议定义

所有命令以 LF（`\n`，十六进制 `0x0A`）结尾。命令名是 ASCII 大写；topic 为 UTF-8 文本；payload 是原始字节。

### 请求

```text
PUBLISH <topic> <payload-length>\n
<payload>\n

SUBSCRIBE <topic>\n
UNSUBSCRIBE <topic>\n
PING\n
STATS\n
FLUSH\n
SHUTDOWN\n
```

例如发布 3 字节载荷 `abc`：

```text
PUBLISH camera/line-1 3\n
abc\n
```

长度只统计 payload 字节，不包括 payload 后的 LF。payload 内可包含 LF、NUL 等任意字节，因此解析器不能按行解析载荷，必须先读取长度再读取精确字节数，最后消费一个 LF。

### 回复

```text
OK\n
OK PONG\n
OK SEQ <sequence>\n
OK SUBSCRIBED <topic>\n
OK UNSUBSCRIBED <topic>\n
OK FLUSHED\n
OK <json-stats>\n
ERR <message>\n
BYE server shutting down\n
```

### 服务端异步事件

```text
EVENT <sequence> <topic> <payload-length>\n
<payload>\n
```

示例：

```text
EVENT 7 camera/line-1 3\n
abc\n
```

### Topic 与通配规则

- topic 不能为空，不能包含 ASCII/Unicode 控制字符，不允许首尾空白。
- topic 内部可以包含空格和 `/` 层级。
- 发布不允许 `*`。
- 订阅允许以 `/*` 结尾的单段通配：`camera/*` 匹配 `camera/1`，不匹配 `camera/1/sub` 或 `other/1`。
- 同一连接同时订阅精确 topic 与通配 topic 时，同一个事件只投递一次。

## 队列与保留语义

1. Broker 在单一全局锁下分配全局序号，保证所有 topic 的发布顺序一致。
2. 每个事件先追加 AOF，成功后才更新内存序号和 topic 日志。
3. 匹配当前订阅连接的事件进入该连接独立 FIFO；不同连接独立 fan-out。
4. 默认每个 topic 保留最近 1000 条事件。新订阅连接建立时先按序号回放保留事件，再接收实时事件。
5. `--retention 0` 时，无订阅方事件不进入内存日志，只在发布当下投递给在线匹配订阅方。
6. 当订阅连接 outbox 满：
   - `reject`：本次 `PUBLISH` 返回显式错误，不产生序号；其他连接不受影响。
   - `block`：发布者等待该连接消费出空位，形成背压，保证该事件不丢，但慢订阅方会拖慢发布。
7. 连接异常断开时，未写入 socket 的 outbox 事件被丢弃；这些事件仍在 topic 保留窗口或 AOF 中。设备/客户端重连后重新 `SUBSCRIBE`，可获得保留窗口内的最近事件。要跨更长停机时间恢复，应使用服务端重启后的 AOF 回放和保留窗口。
8. 已进入 TCP 发送缓冲区或已被客户端读取的事件不会重复投递；客户端应使用全局 `sequence` 做业务幂等。

## AOF 持久化与恢复

AOF 文件默认是当前工作目录下的 `.linebus.aof`。文件格式为：

```text
LINEBUS-AOF/1
EVENT 1 camera/1 3
abc
EVENT 2 sensor/temp 4
23.5
```

- `PUBLISH` 成功响应前执行 `write + flush + fsync`。
- AOF 记录顺序与命令拿到全局序号的顺序一致。
- 启动时读取完整事件记录，恢复每 topic 保留日志与下一个序号。
- 如果进程崩溃导致最后一条记录只写了一半，启动时截断这条不完整尾部；更早的完整记录仍恢复。
- AOF 中间记录损坏、序号不连续或 magic 不匹配属于严重损坏，服务拒绝启动并报告错误。
- `FLUSH` 清空内存 topic 日志、连接待发送事件，并截断 AOF；之后序号从 1 重新开始。

## 并发模型

- 接受线程负责 accept；每个连接有独立 reader 和 writer 线程。
- reader 负责协议解析和命令执行。
- writer 只从该连接的 outbox 取事件/回复并写入 socket，避免事件和命令响应交叉。
- `Broker.lock` 是一把 `RLock`，所有条件等待也使用该锁。
- 全局序号、topic 保留 deque、订阅 pattern、outbox 容量、FLUSH 均在同一锁域内变更，避免数据竞争。
- 事件发送给各订阅方的相对顺序与全局序号一致；不同连接由于网络速度不同，不保证同时收到，但各自不重排。

## 错误处理

- 未知命令、非法 topic、缺少参数、队列满：返回 `ERR ...`，连接继续可用。
- 无法确定后续帧边界的协议错误（例如 payload 结束符错误、非法长度、非法 UTF-8 topic、超长命令）：返回 `ERR ...` 后关闭当前连接。
- 服务捕获会话内未知异常，单个畸形请求不会终止服务。
- `SHUTDOWN` 会设置关闭标记、关闭监听 socket，并向每个连接 outbox 放入 `BYE server shutting down`。

`STATS` 返回 JSON，例如：

```json
{
  "connections": 2,
  "topics": 3,
  "retained_events": 120,
  "subscriptions": 2,
  "queued_events": 0,
  "last_sequence": 120,
  "total_published": 120,
  "total_rejected": 0,
  "retention": 1000,
  "queue_capacity": 1000,
  "full_strategy": "reject"
}
```

## 测试

运行：

```bash
python3 -m pytest tests/ -v
```

当前测试覆盖：

- 空载荷、空格/制表符/换行/NUL 载荷、任意字节分片解析、事件往返。
- 超长命令、非法长度、非法 payload 结束符、未知命令、非法 UTF-8。
- 订阅前/订阅后发布、多 topic、通配订阅、重叠订阅去重。
- 多订阅方 fan-out 与断连隔离。
- 默认保留最近 N、保留 0 丢弃、保留窗口淘汰。
- 队列满 reject 与 block 两种策略。
- 全局序号单调递增和多 topic 顺序。
- AOF 任意字节、顺序、重启恢复、序号连续、FLUSH、半条尾部记录恢复。
- 12 个客户端（6 发布 + 6 订阅）120 条事件并发，无丢失、无重复、无崩溃。
- 非法命令和协议错误回复。
- 优雅 shutdown 的 `BYE` 通知。

测试均在标准库网络会话上运行，不要求外部服务或第三方运行时包。

## 无第三方依赖

运行时代码没有安装或导入任何第三方包。开发环境若需要运行测试，仅安装：

```bash
python3 -m pip install pytest
```
