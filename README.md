# minidns

内网自用的迷你 DNS 服务器：**纯 Python 标准库**实现（无任何第三方依赖），
DNS 报文的每个字节都自己拼、自己解。支持权威 zone、递归转发 + TTL 缓存、
UDP/TCP 双传输。

## 功能一览

- 报文编解码：Header / Question / ResourceRecord，Flags 全字段位操作，
  名字压缩（0xC0 指针）编码与解码，指针环检测（FORMERR）
- 记录类型：A、AAAA、CNAME、MX、TXT、NS（SOA 可解析）；未知类型（如
  TYPE65）rdata 原样保留，不崩
- 权威模式：BIND 风格 zone 文件（`$ORIGIN`/`$TTL`/`@`/相对名/行尾注释/
  括号续行），一个目录加载多个 zone，同名多条记录 round-robin，
  CNAME 链跟随（断链 NXDOMAIN、成环 SERVFAIL）
- 递归模式：未命中 zone 的查询转发上游，应答记录按各自 TTL 缓存，
  上游超时（默认 3s）返回 SERVFAIL；相同并发查询 singleflight 合并
- 传输：UDP（默认 5353，免 root）+ TCP（两字节长度前缀）；
  UDP 应答超 512 字节置 TC=1 并清空 Answer，客户端改走 TCP 拿全量
- 访问日志：时间、客户端、查询名、类型、RCODE、耗时、缓存命中标记

## 快速开始

```bash
# 权威 + 递归（上游阿里 DNS）
./bin/minidns serve --zones ./zones --port 5353 --upstream 223.5.5.5

# 调试用查询（自动解析应答、TC 时自动改走 TCP）
./bin/minidns query --server 127.0.0.1:5353 example.com A
./bin/minidns query --server 127.0.0.1:5353 www.example.com AAAA --tcp
```

也可以用 `python3 -m minidns serve ...` / `python3 -m minidns query ...`。

## DNS 报文结构

```
+-------------------+-------------------+
| ID (16)           | FLAGS (16)        |   FLAGS: QR Opcode AA TC RD RA Z RCODE
+-------------------+-------------------+
| QDCOUNT | ANCOUNT | NSCOUNT | ARCOUNT |   各 16 位
+-------------------+-------------------+
| Question 段 ...                        |   名字 + QTYPE(16) + QCLASS(16)
+-------------------+-------------------+
| Answer / Authority / Additional ...    |   资源记录：名字 TYPE CLASS TTL RDLENGTH RDATA
+-------------------+-------------------+
```

- **名字编码**：每个标签前 1 字节长度，域名以 0 字节结尾，如
  `www.example.com` → `03 77 77 77 07 65 78 61 6d 70 6c 65 03 63 6f 6d 00`
- **名字压缩**：出现过的域名后缀可用两字节指针 `0xC000 | offset` 代替。
  本实现编码时尽量复用 Question 里的名字；解码时顺指针还原完整域名，
  并检测指针环（A→B→A），成环按 FORMERR 拒绝
- **RCODE**：NOERROR=0、FORMERR=1、SERVFAIL=2、NXDOMAIN=3、NOTIMP=4
- **TCP**：报文前加两字节大端长度前缀

## zone 文件格式

```bind
$ORIGIN example.com.
$TTL 300

@   IN  SOA ns1.example.com. admin.example.com. (
        2026092001 7200 3600 1209600 300 )
    IN  NS  ns1
www IN  A   192.168.1.20        ; 行尾注释
    IN  A   192.168.1.21        ; 空 owner = 上一条名字，多条 A 轮询
web IN  CNAME   www             ; CNAME 链：查询 web 会带出 www 的 A
mail    IN  MX  10 mail.example.com.
txt IN  TXT "hello" (           ; 括号续行
        "world" )
```

规则：`@` 表示当前 `$ORIGIN`；不带点的名字自动补上 origin；TTL 与 `IN`
可省略（用 `$TTL` 默认值）；`;` 到行尾是注释；括号跨行。解析错误会报
文件名 + 行号。`--zones` 目录下的所有文件启动时全部加载。

## 两种模式

1. **权威模式**：查询名命中已加载的 zone → AA=1 直接应答；
   名字不存在 NXDOMAIN；名字存在但类型不符 NOERROR 空应答（NODATA）；
   CNAME 链跟随，链断 NXDOMAIN。
2. **递归模式**：未命中任何 zone → 查缓存（key = 名字+类型+类，TTL 真实
   时间倒计时）→ 未命中转发 `--upstream`，应答记录按各自 TTL 缓存后原样
   转回客户端（ID 改写回客户端的）；上游超时 SERVFAIL；同一名字的并发
   查询只发一次上游请求（singleflight）。

## 测试

```bash
python3 -m pytest tests/ -q
```

覆盖：报文 roundtrip（字节级一致）、压缩指针（产生/还原/环检测）、
zone 解析（含错误行号）、round-robin、CNAME 链、缓存命中/过期/分类型、
UDP/TCP 真实服务集成（临时端口、并发不串包、畸形报文 FORMERR/丢弃、
超 512 字节 UDP 截断 + TCP 拿全）。测试只用 socket 手工发包，
不依赖任何第三方 DNS 库。

## 目录结构

```
minidns/
  protocol.py   报文编解码、名字压缩
  zone.py       zone 文件解析、区域存储（轮询/CNAME 链）
  cache.py      TTL 缓存
  server.py     UDP/TCP 服务、递归转发、singleflight、访问日志
  cli.py        serve / query 子命令
bin/minidns     命令行入口
zones/          示例 zone
tests/          pytest 测试
```
