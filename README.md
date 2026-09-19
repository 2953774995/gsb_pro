# minibroker

一个迷你版发布/订阅消息队列，仅使用 Python 标准库实现（被测代码零第三方依赖，测试框架 pytest 除外）。

- TCP 服务端（默认端口 `7379`，每连接一个读线程 + 一个写线程）
- 自定义文本协议：命令以 `\n` 结尾，载荷按长度前缀编码，可承载任意字节
- 内存 FIFO 队列、fan-out 投递、通配订阅、保留消息（retained backlog）
- AOF 追加持久化，重启后恢复消息与全局序号
- Python 客户端 SDK（`BrokerClient`）与交互式命令行（`mb-cli`）

## 快速开始

```bash
# 启动 broker（默认 127.0.0.1:7379，AOF 写入 ./.broker.aof）
python3 -m minibroker --port 7379

# 另开一个终端，交互式客户端
python3 -m minibroker.cli --port 7379     # 或 ./mb-cli
```

`mb-cli` 内：

```
mb> subscribe news/*
subscribed to news/*
mb> publish news/tech hello world
ok (seq=1)
[msg #1] news/tech: hello world        # 实时推送
mb> stats
mb> quit
```

SDK 用法：

```python
from minibroker import BrokerClient

sub = BrokerClient(port=7379).connect()
sub.subscribe("news/*")

pub = BrokerClient(port=7379).connect()
seq = pub.publish("news/tech", b"hello")   # 返回全局序号

msg = sub.next_message(timeout=5)          # 阻塞取消息；超时返回 None
print(msg.seq, msg.topic, msg.payload)
```

## 协议定义

每个**头部**是一行以 `\n` 结尾的文本；**载荷**为长度前缀的原始字节，因此可以包含空格、制表符、换行、NUL 等任意字节。单条命令（头部+载荷）默认上限 1 MiB（`--max-command-size` 可调），超限返回 `ERR command too large`。

客户端 → 服务端：

```
PUBLISH <topic> <payload_len>\n<payload bytes>
SUBSCRIBE <pattern>\n                 # pattern 为 topic 或 <topic>/*
UNSUBSCRIBE <pattern>\n
PING\n
STATS\n
FLUSH\n
SHUTDOWN\n
```

服务端 → 客户端：

```
OK [text]\n                           # PUBLISH 的 OK 携带分配的序号，如 "OK 42"
ERR <message>\n                       # 所有错误统一 ERR 前缀
PONG\n
MSG <seq> <topic> <payload_len>\n<payload bytes>   # 异步推送
STATS <payload_len>\n<json bytes>
BYE <reason>\n                        # 服务端关闭前通知所有客户端
```

示例（`PUBLISH t 5\nhello` 的响应为 `OK 1\n`，订阅者收到 `MSG 1 t 5\nhello`）。

### Topic 与通配符

- topic：非空、≤512 字符，不得包含空白/控制字符与 `*`。
- 订阅模式：`topic`（精确匹配）或 `topic/*`（匹配 `topic/` 前缀下任意非空后缀，可跨多级，如 `news/*` 匹配 `news/a` 与 `news/a/b`，不匹配 `news` 本身）。
- 同一连接可用多个模式订阅多个 topic；若多个模式同时匹配一条消息，该连接只收到一份。

## 队列语义

- **FIFO + fan-out**：每个 topic 的消息按发布顺序投递；每个匹配的订阅者各自收到一份完整副本。
- **全局序号**：所有 PUBLISH 共享一个单调递增序号（跨 topic），随每条 `MSG` 下发。
- **保留策略（retention，默认 1000）**：每个 topic 保留最近 N 条消息；新订阅者订阅时先按序号顺序补投这些保留消息，再接收实时消息。`--retention 0` 表示无订阅者时直接丢弃（仅实时投递）。
- **背压（队列长度上限）**：每个订阅连接有界缓冲（`--max-pending`，默认 10000）。缓冲满时 PUBLISH 行为由 `--on-full` 决定：
  - `error`（默认）：整条 PUBLISH 失败，返回 `ERR subscriber queue full ...`，消息不落盘、不投递；
  - `block`：发布者阻塞，直到所有匹配订阅者的缓冲有空间（订阅者断开则报错返回）。
  - 保留 backlog 本身超过 retention 时淘汰最旧消息（保留最近 N 条）。
- **FLUSH**：清空所有保留消息并重置 AOF（通过 `#SEQ` 检查点保持序号继续递增，不回退）；已推送到订阅者缓冲的在途消息不召回。
- **SHUTDOWN**：先向所有连接发送 `BYE`，待发送缓冲冲刷后优雅退出。

## 持久化与恢复

所有 PUBLISH 在应用到内存状态**之前**追加写入 AOF（默认 `./.broker.aof`，`--aof` 可改路径，`--no-aof` 关闭，`--aof-fsync` 每次刷盘）。AOF 写入在 broker 全局锁内完成，因此文件顺序与执行顺序一致。

记录格式（二进制安全）：

```
AOF1 <seq> <topic_len> <payload_len>\n<topic bytes><payload bytes>
#SEQ <seq>\n        # FLUSH 写入的序号检查点
```

启动时回放 AOF 恢复各 topic 的保留队列与全局序号；文件尾部的不完整记录（崩溃撕裂写）会被安全忽略。

## 架构与代码组织

```
minibroker/
  protocol.py       协议解析/序列化、topic 与通配符校验、帧编解码
  store.py          消息存储：每 topic 有界 FIFO backlog（retention）
  subscriptions.py  订阅表：conn_id -> {pattern: mailbox}，匹配与去重
  aof.py            AOF 追加写入与容错回放
  broker.py         核心：全局序号、fan-out、背压策略、FLUSH/STATS（单 RLock 保护全部状态）
  server.py         TCP 网络层：accept 循环、每连接读/写线程、命令分发、优雅关闭
  client.py         BrokerClient SDK（后台读线程解复用 MSG 推送与命令响应）
  cli.py            mb-cli 交互式客户端
  __main__.py       python3 -m minibroker 启动服务端
tests/              pytest 测试套件
mb-cli              CLI 启动脚本
```

**并发模型**：broker 核心用一把 `threading.RLock` 保护序号、存储、订阅表与 AOF，因此每个订阅者的邮箱严格按发布顺序收到消息，AOF 顺序与执行顺序一致。网络层每连接一个读线程（解析命令）+ 一个写线程（所有出站字节都经过该连接的有界邮箱串行化，socket 写永不并发）。连接异常断开时其订阅被清理，未消费消息随连接缓冲一起丢弃（保留策略内的消息仍留在 backlog 中），不影响其他订阅者。

## 服务端参数

```
python3 -m minibroker --help
  --host / --port        监听地址（默认 127.0.0.1:7379）
  --retention N          每 topic 保留消息数（默认 1000，0 = 无订阅者即丢弃）
  --max-pending N        每订阅连接的最大待投递缓冲（默认 10000）
  --on-full error|block  订阅者缓冲满时 PUBLISH 报错或阻塞（默认 error）
  --aof PATH / --no-aof  AOF 文件路径（默认 ./.broker.aof）/ 关闭持久化
  --aof-fsync            每次追加后 fsync
  --max-command-size N   单条命令大小上限（默认 1MiB）
```

## 客户端 SDK

```python
BrokerClient(host="127.0.0.1", port=7379, timeout=10)
  .connect()            # 建立连接（支持 with 语句）
  .close()
  .publish(topic, payload) -> int      # payload 为 bytes 或 str，返回全局序号
  .subscribe(pattern)                  # 可多次调用订阅多个 topic / 通配符
  .unsubscribe(pattern)
  .next_message(timeout=None)          # 阻塞取推送；超时返回 None；连接关闭抛 BrokerClosed
  .ping() / .stats() / .flush() / .shutdown()
```

服务端返回 `ERR` 时 SDK 抛出 `BrokerError`；连接被关闭（如对端 SHUTDOWN）时抛出 `BrokerClosed`。

## 测试

```bash
python3 -m pytest tests/ -v
```

覆盖：协议解析边界（空载荷、含空格/制表符/换行/二进制载荷往返、超长命令）、pub/sub 语义（订阅前/后发布、fan-out、通配符、退订）、保留与丢弃策略、全局序号单调性、AOF 重启恢复（含序号连续性、FLUSH 检查点、撕裂写容错）、并发（12 客户端同时发布/订阅不丢不重、订阅churn、慢订阅者断开）、非法命令与协议错误回复、优雅关闭与 BYE 通知。

> 说明：测试默认在真实 TCP 回环连接上运行；在禁止绑定 TCP 端口的沙箱环境中，同一套测试会自动改用 `socket.socketpair()` 注入连接，端到端地跑完整个协议/客户端/服务端栈（仅 2 个显式 TCP 冒烟测试会跳过）。
