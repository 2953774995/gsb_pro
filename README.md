# minidns

内网自用的迷你 DNS 服务器：**权威 zone + 递归转发 + TTL 缓存**，纯 Python 标准库实现（只用到 `socket` / `struct` / `threading` 等），DNS 报文的每个字节都自己拼、自己解，不依赖 dnspython 之类的第三方包。

## 功能一览

- 完整的 DNS 报文编解码：Header / Question / Resource Record、Flags 位操作、**名字压缩（0xC0 指针，含指针环检测）**
- 记录类型：A、AAAA、CNAME、MX、TXT、NS（外加 SOA）；不认识的类型（如 TYPE65）RDATA 原样保留，不会崩
- 权威模式：BIND 风格 zone 文件（`$ORIGIN`、`$TTL`、相对名、`@`、行尾注释、括号续行），同名多条记录**轮询（round-robin）**，CNAME 链跟随、断链 NXDOMAIN
- 递归模式：非权威查询转发上游 DNS，应答按各自 TTL 缓存，上游超时（默认 3s）回 SERVFAIL，同一名字的并发查询合并为一次上游请求（singleflight）
- 传输：UDP 为主（多线程并发），应答超 512 字节置 `TC=1` 且不发 Answer；TCP（两字节长度前缀）返回完整内容
- 访问日志：时间、客户端、查询名、类型、RCODE、耗时毫秒、缓存命中标记

## 快速开始

```bash
# 权威 + 递归：加载 ./zones 下所有 zone 文件，其余查询转发 223.5.5.5
python3 -m minidns serve --zones ./zones --port 5353 --upstream 223.5.5.5
# 或用包装脚本
bin/minidns serve --zones ./zones --port 5353 --upstream 223.5.5.5

# 调试查询（先发 UDP，应答带 TC 时自动改走 TCP）
python3 -m minidns query --server 127.0.0.1:5353 www.example.com A
python3 -m minidns query --server 127.0.0.1:5353 --tcp big.huge.test TXT
```

不加 `--upstream` 就是纯权威模式：不在 zone 里的名字回 `REFUSED`。

`serve` 参数：`--zones`（zone 目录，必填）、`--port`（默认 5353，不需要 root）、`--host`、`--upstream`、`--upstream-port`（默认 53）、`--timeout`（上游超时，默认 3 秒）、`-v`（调试日志）。

## DNS 报文结构

```
+------------------- 12 字节 Header -------------------+
| ID (2) | FLAGS (2) | QDCOUNT | ANCOUNT | NSCOUNT | ARCOUNT |
+------------------------------------------------------+
| Question 段（QDCOUNT 条）                              |
| Answer / Authority / Additional 段（Resource Record）   |
```

**FLAGS 各位**（本实现逐位编解码）：

```
bit 15    QR      0=查询 1=应答
bit 14-11 Opcode  0=QUERY
bit 10    AA      权威应答
bit  9    TC      截断（UDP 超 512 字节时置位，客户端应改走 TCP）
bit  8    RD      期望递归
bit  7    RA      支持递归
bit  3-0  RCODE   0=NOERROR 1=FORMERR 2=SERVFAIL 3=NXDOMAIN 4=NOTIMP
```

**域名编码**：每个标签前 1 字节长度，以 0 字节结尾（`www.example.com` → `03 www 07 example 03 com 00`）。比较大小写不敏感。

**名字压缩**：报文中出现过的域名后缀，再次出现时可用两字节指针（高两位 `11`，低 14 位为偏移）引用。编码时尽量复用 Question 里的名字；解码时顺指针还原完整域名，并用已访问指针集合检测**指针环**（A 指 B、B 指 A），发现即按 FORMERR 拒绝，不会死循环。

**Resource Record**：`NAME | TYPE(2) | CLASS(2) | TTL(4) | RDLENGTH(2) | RDATA`。RDATA 按类型解释：A=4 字节 IPv4，AAAA=16 字节 IPv6，CNAME/NS=域名（可压缩），MX=2 字节优先级+域名，TXT=若干「长度+字符串」，未知类型=原始字节透传。

**TCP 传输**：报文前加 2 字节大端长度前缀；UDP 应答超过 512 字节时只回 `TC=1` 的空应答，由客户端改走 TCP 拿全量。

## zone 文件格式

BIND 风格，一个目录可放多个 `.zone` 文件，启动时全部加载（没写 `$ORIGIN` 时按文件名推导，如 `example.com.zone` → `example.com`）：

```
$ORIGIN example.com.
$TTL 300                      ; 支持 300 / 30m / 1h / 2d / 1w

@       IN  SOA ns1 admin (   ; @ 表示 origin；括号内可跨多行
        2026092001            ; 行尾 ; 是注释
        7200 3600 1209600 300 )
@       IN  NS      ns1
        IN  MX 10   mail      ; 行首留空 = 沿用上一行的名字
www     300 IN  A   192.168.1.10
www     300 IN  A   192.168.1.11   ; 同名多条 -> 应答时轮询
web     IN  CNAME   www            ; 相对名自动补 origin
mail    IN  AAAA    fd00::25
txt     IN  TXT     "hello world"  "k=v;分号要引号"
```

- 名字：`@`=origin；以 `.` 结尾为绝对名；其余自动拼上 origin
- TTL、CLASS(IN) 可省略，顺序任意；省略 TTL 时用 `$TTL`
- 解析错误会报 **文件名:行号**，例如 `zones/example.com.zone:12: unknown record type: 'FOO'`

**CNAME 链**：查 `web` 时，应答里带 `web CNAME www` 和 `www A ...`；链断（目标不在任何已加载 zone）回 `NXDOMAIN`。

## 递归与缓存

- 查询名不属于任何已加载 zone 且配置了 `--upstream`：转发上游，应答原样转回客户端
- Answer 段记录按 `(名字, 类型, 类)` 分组缓存，各按自己的 TTL 计期（真实时间倒计时），到期自动失效；回给客户端的 TTL 是剩余秒数
- 上游超时 / 出错 → `SERVFAIL`
- singleflight：同一时刻多个客户端查同一个未缓存名字，只向上游发一个请求，其余等结果

## 访问日志

```
2026-09-20 12:00:01,123 INFO 127.0.0.1:53535 www.example.com A NOERROR 0.8ms cache=-
2026-09-20 12:00:02,456 INFO 127.0.0.1:53536 baidu.com A NOERROR 15.2ms cache=MISS
2026-09-20 12:00:03,010 INFO 127.0.0.1:53536 baidu.com A NOERROR 0.3ms cache=HIT
```

## 测试

```bash
python3 -m pytest        # 全部测试（网络集成测试需要能 bind socket 的环境）
```

覆盖：报文 roundtrip（字节级一致）、压缩指针（产生/还原/指针环）、zone 解析（含报错行号）、round-robin、CNAME 链与断链、缓存命中/过期/分类、UDP/TCP 真实服务集成（并发不串包、畸形报文 FORMERR/丢弃、超 512 字节截断与 TCP 全量）、递归转发与 singleflight。测试全部用 `socket` 手工发包，不引第三方 DNS 库。

> 注：网络集成测试在禁止 socket 的沙箱环境里会自动跳过（`skipped`），在正常环境才会执行。

## 项目结构

```
minidns/
  protocol.py   报文编解码：Header/Question/RR、压缩指针、各类型 RDATA
  zone.py       zone 文件解析器 + Zone（轮询、CNAME 链）
  cache.py      TTL 缓存（真实时间倒计时）
  resolver.py   上游转发 + singleflight
  server.py     UDP/TCP 服务、查询处理、访问日志
  cli.py        serve / query 子命令
zones/          示例 zone 文件
tests/          pytest 测试
```
