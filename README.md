# linebus

`linebus` 是一个面向车间质检场景的轻量事件分发服务：相机、传感器等工位设备把质检事件发布到 topic，MES 与车间电子看板可作为独立订阅方实时 fan-out 消费。服务端与客户端 SDK 全部使用 **Python 3.8+ 标准库** 实现，除 pytest 外没有任何第三方依赖。

## 特性

- 自定义、可承载任意字节的长度前缀文本协议。
- TCP 服务默认监听 `0.0.0.0:7379`，支持 `--port`、命令大小限制等参数。
- 命令：`PUBLISH`、`SUBSCRIBE`、`UNSUBSCRIBE`、`PING`、`STATS`、`FLUSH`、`SHUTDOWN`。
- 每个连接可同时订阅多个 topic，支持 `namespace/*` 末尾通配。
- 每条事件有全局单调递增序号，服务端按发布顺序向每个订阅方 FIFO 投递。
- 多订阅方独立队列，慢订阅方按 backpressure 策略阻塞或显式报错，互不影响。
- 无订阅方时按 topic 保留最近 N 条（默认 1000，`0` 表示不保留）。
- 所有发布事件顺序追加到 `.linebus.aof`，启动时回放并恢复事件与序号。
- 多线程网络模型，topic、队列、订阅表和 AOF 均通过同一 broker 锁保证一致性。
- 提供 `LinebusClient` SDK 与交互式 `lb-cli`。
- `SHUTDOWN` 先唤醒/通知在线连接，再关闭监听 socket、连接和 AOF。

## 目录结构

```text
linebus/
├── protocol.py     # 文本帧解析/序列化、topic 校验、通配匹配
├── storage.py      # 按 topic 组织的内存 FIFO/最近 N 条事件存储
├── persistence.py  # AOF 追加、FLUSH 截断、启动回放和损坏检测
├── broker.py       # 线程安全订阅表、fan-out 队列、序号与 backpressure
├── server.py       # 多线程 TCP 服务与命令分发
├── client.py       # LinebusClient SDK
└── cli.py          # lb-cli 交互式命令行
bin/
├── linebus-server  # python3 -m linebus.server 包装脚本
└── lb-cli          # python3 -m linebus 包装脚本
tests/              # pytest 测试
```

## 协议定义

命令是 ASCII 文本头，以 `\n` 结尾，也兼容 `\r\n`。需要载荷的命令在头部最后一个字段声明字节数，随后紧接对应数量的原始字节；载荷不需要转义，因此可以包含空格、制表符、换行、`\0` 等任意内容。

### 客户端到服务端

```text
PING\n
SUBSCRIBE <topic>\n
UNSUBSCRIBE <topic>\n
STATS\n
FLUSH\n
SHUTDOWN\n
PUBLISH <topic> <payload-length>\n
<payload bytes>
```

示例：

```text
PUBLISH quality/camera-1 11\n
hello world
```

### 服务端回复

```text
OK PONG\n
OK SUBSCRIBED\n
OK UNSUBSCRIBED\n
OK PUBLISHED <sequence>\n
OK FLUSHED\n
OK SHUTDOWN\n
OK SERVER_SHUTDOWN\n
ERR <message>\n
EVENT <sequence> <topic> <payload-length>\n
<payload bytes>
OK STATS <payload-length>\n
<key>=<value> key=<value> ...
```

`EVENT` 是订阅成功后的异步推送。一个连接同时命中精确订阅和通配订阅时，服务端为同一连接的每个具体 topic 只维护一份队列，因此不会重复投递。

### 大小限制

默认单条命令（头部 + 载荷）最大 `1 MiB`。超长命令返回 `ERR`，服务不会崩溃。生产服务可用：

```bash
python3 -m linebus.server --max-command-size 1048576
```

调整限制。

### Topic 与通配规则

- topic 不允许为空、空白字符或 ASCII 控制字符，最大 255 字节。
- topic 可包含 `/`、字母、数字、`-`、`_`、`.` 等非空白字符。
- 只有订阅模式允许 `*`，且必须是末尾通配：`<prefix>/*`。
- `quality/*` 匹配：
  - `quality`
  - `quality/camera-1`
  - `quality/camera-1/defect`
- `quality/*` 不匹配 `quality-other/x`。

## 队列、保留与不丢事件语义

### 新订阅与最近 N 条

broker 按 topic 保留最近 N 条无消费事件：

- `--retention 1000`（默认）：新订阅建立时会先收到该 topic 最近最多 1000 条历史，然后接收实时事件。
- `--retention 0`：没有匹配在线订阅时事件只写 AOF，不进入内存回放；这满足“无订阅方丢弃”的显式配置。

### Fan-out 与在线积压

每个在线连接拥有独立的“订阅连接 × topic”FIFO 队列。多个订阅方各自消费同一份事件，某个连接断开或积压不会删除其他连接的事件。

每条订阅连接/topic 的实时队列长度由 `--queue-capacity` 控制，默认 1000；`0` 表示不限长。队列满时由 `--queue-full-policy` 决定：

- `block`（默认）：`PUBLISH` 等待慢订阅方取走事件后继续，尽量保证在线事件不丢。
- `error`：立即返回 `ERR ... queue ... is full; policy=error`，由业务方决定重试或上报。

> 注意：TCP 客户端所在主机断电、操作系统崩溃且连接未正常退出时，任何纯内存队列都无法做到绝对不丢。linebus 的“不丢”由三层保证：AOF 持久化发布事实、默认最近 N 条重放、在线队列 block backpressure。持久化消费者确认机制（consumer ack）不属于本 PRD 的命令集。

## AOF 持久化

默认 AOF 文件为当前工作目录下的 `.linebus.aof`。记录使用长度前缀，载荷可包含任意字节：

```text
P <sequence> <topic-byte-length> <payload-length>\n
<topic bytes><payload bytes>
```

示例：

```text
P 1 16 4
quality/camera-1FAIL
```

`FLUSH` 会在 broker 锁内清空内存、订阅方积压，并把 AOF 替换为：

```text
FLUSH 1
```

发布命令先在执行序列中分配全局序号，再追加 AOF，AOF 写入成功后向订阅者入队。多线程发布由同一把 broker 锁串行化，因此 AOF 顺序与执行顺序一致。启动时如果发现尾部半个记录或序号断裂，会抛出 AOF 错误而不是静默截断，避免人工误判数据已恢复。

默认每条事件 `flush + fsync`。测试或对吞吐要求更高的部署可以使用 `--no-fsync`，仍会调用 `flush()` 交给操作系统写入。

## 快速开始

### 启动服务

```bash
python3 -m linebus.server --host 0.0.0.0 --port 7379
# 或
bin/linebus-server --port 7379
```

常用参数：

```bash
python3 -m linebus.server \
  --host 0.0.0.0 \
  --port 7379 \
  --retention 1000 \
  --queue-capacity 1000 \
  --queue-full-policy block \
  --aof .linebus.aof
```

参数说明：

- `--host`：监听地址，默认 `0.0.0.0`。
- `--port`：监听端口，默认 `7379`。
- `--retention`：无匹配在线订阅时每 topic 保留的最近事件数，默认 `1000`。
- `--queue-capacity`：每个订阅连接/topic 的实时队列长度，默认 `1000`，`0` 为不限。
- `--queue-full-policy`：`block`（默认）或 `error`。
- `--aof`：AOF 路径，默认 `.linebus.aof`。
- `--no-fsync`：每条记录 flush 但不 fsync。
- `--max-command-size`：单命令字节数上限，默认 `1048576`。

### 交互式客户端

```bash
python3 -m linebus --host 127.0.0.1 --port 7379
# 或
bin/lb-cli --host 127.0.0.1 --port 7379
```

进入后：

```text
linebus> ping
linebus> publish quality/camera-1 panel scratch detected
linebus> subscribe quality/camera-1
subscribed ...
EVENT seq=1 topic=quality/camera-1 len=... payload=b'...'
linebus> stats
linebus> flush
linebus> shutdown
linebus> quit
```

CLI 的 `publish` 以 UTF-8 文本发送。若需要发送二进制载荷，请使用 Python SDK。

## Python SDK

```python
from linebus import LinebusClient

publisher = LinebusClient("127.0.0.1", 7379).connect()
sequence = publisher.publish("quality/camera-1", b"\x00\x01\x02 raw event\n")
print("published", sequence)
publisher.close()

subscriber = LinebusClient("127.0.0.1", 7379).connect()
subscriber.subscribe("quality/camera-1")

while True:
    message = subscriber.next_message()  # 阻塞等待
    print(message.sequence, message.topic, message.payload)
```

同时支持上下文管理器：

```python
with LinebusClient("127.0.0.1", 7379) as client:
    print(client.ping())
```

客户端方法：

- `connect()` / `close()`
- `ping()`
- `publish(topic, payload=b"") -> sequence`
- `subscribe(topic)` / `unsubscribe(topic)`
- `next_message(timeout=None) -> Message`
- `stats()` / `flush()` / `shutdown()`

## 架构与并发模型

- 每个 TCP 连接启动一个读线程和一个投递线程。
- 读线程负责解析帧、校验命令并调用 broker。
- 投递线程从该连接的 subscriber 中取最旧事件，按序号推送。
- broker 使用 `threading.Condition` 保护：
  - 全局序号；
  - 每 topic 最近 N 条；
  - topic -> 订阅方集合；
  - 每连接/topic 的 FIFO；
  - STATS 计数；
  - FLUSH/SHUTDOWN 状态。
- AOF 追加也在 broker 锁内完成，保证持久化顺序和发布顺序一致。
- 网络层发送使用连接级 `send_lock`，避免命令回复与异步事件交错写坏字节流。
- 单个连接的异常由连接线程隔离，清理订阅后继续服务其他连接。

## 运行测试

```bash
python3 -m pytest tests/ -v
```

测试覆盖：

- 空载荷、空格、制表符、换行、NUL 字节的协议往返；
- 超长命令、畸形头部、非法长度和非法 topic；
- 订阅前发布（最近 N 条回放）与订阅后实时发布；
- 多订阅方 fan-out、断开重连、互不影响；
- retention=1000/0；
- 全局序号单调递增；
- block/error 两种队列满策略；
- 精确订阅 + 通配订阅不重复；
- AOF 重启恢复、FLUSH 截断、损坏/截断检测；
- 12 个并发连接（6 订阅 + 6 发布）不崩溃、不丢失、不重复；
- 非法命令、协议错误和优雅 SHUTDOWN。

> 当前测试使用 `socket.socketpair()` 驱动真实的服务端 socket I/O 代码路径，因此在禁止绑定 TCP 端口的沙箱中也可运行；正常系统上服务本身仍使用标准 AF_INET TCP。

## 手动验收示例

终端 1：

```bash
rm -f .linebus.aof
python3 -m linebus.server --port 7379
```

终端 2：

```bash
bin/lb-cli
linebus> subscribe quality/camera-1
```

终端 3：

```bash
bin/lb-cli
linebus> publish quality/camera-1 defect-code-A
linebus> publish quality/camera-1 defect-code-B
```

终端 2 应实时收到序号递增的两条事件。随后重启服务端并重新订阅，默认 retention 会回放 `.linebus.aof` 中仍保留的事件；重启后再次发布，序号从 AOF 中最大序号继续递增。
