# gwadmin

工厂边缘网关的本地管理 Agent。面向 ARM 工控机、无外网、资源受限的产线环境，
**仅使用 Python 标准库**（`socket` / `threading` / `json` 等），HTTP/1.1 协议层
完全自实现——不依赖 `http.server`、`BaseHTTPRequestHandler` 或任何第三方包
（测试框架 pytest 除外）。

## 特性

- **自实现 HTTP/1.1 协议层**
  - 请求解析：请求行 / 请求头（键大小写不敏感、重复头按 RFC 7230 合并为逗号
    分隔）/ 按 `Content-Length` 精确读取请求体；非法长度 → 400，超过 16MB → 413
  - 请求行 + 头部超过 8KB → 400；缺失 `Host`（HTTP/1.1）→ 400；非法方法字符、
    坏版本号、畸形头格式 → 400
  - query string 解析为 `name -> [values]` 映射
  - 响应序列化：状态行 + `Content-Type` / `Content-Length` / `Connection` /
    `Server` / `Date`；覆盖 200/301/302/400/403/404/405/413/500 等状态码并
    提供默认错误页；HEAD 只发头但 `Content-Length` 正确
  - Keep-Alive：HTTP/1.1 默认保持连接，`Connection: close` 正确关闭；
    空闲 30s（可配）自动断开
- **路由与处理器**：`Router` 支持 GET/POST/PUT/DELETE（HEAD 自动复用 GET），
  `/api/devices/:id` 路径参数，未注册路径 404，方法不匹配 405 + `Allow` 头；
  处理器签名 `handler(request) -> (status, headers, body)`，body 支持
  bytes/str/None；支持 `before_request` / `after_request` 中间件钩子
- **静态文件**：按扩展名内置 MIME 表；目录请求返回 `index.html`，无索引 → 403；
  路径规范化后强制限制在根目录内，任何 `..` / 编码穿越（`%2e%2e` 等）一律 404
- **管理 API**
  - `GET /api/status`：版本、运行时长、工作线程数、已处理请求数
  - `GET /api/config`：当前生效配置
  - `POST /api/config`：表单或 JSON 配置，校验后原子化持久化到本地 JSON 文件，
    非法配置 → 400 并说明原因
- **并发与健壮性**：每连接一线程（信号量限流，过载返回 503）；畸形请求只会
  得到 400/关闭连接，绝不会打挂进程；未捕获异常统一兜底为 500 且不泄漏堆栈；
  SIGINT/SIGTERM 干净关机（停止接受新连接并关闭现有连接）
- **可观测**：访问日志输出到 stdout（时间、来源、方法、路径、状态码、耗时 ms）

## 运行

```bash
python3 -m gwadmin --host 0.0.0.0 --port 8080 --root www --workers 4
```

参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--host` | `0.0.0.0` | 监听地址 |
| `--port` | `8080` | 监听端口 |
| `--root` | `www` | 静态页面根目录 |
| `--workers` | `4` | 工作线程数（同时用于连接池容量与 `/api/status` 上报） |
| `--config` | `gwadmin-config.json` | 配置持久化文件路径 |
| `--idle-timeout` | `30` | Keep-Alive 空闲超时（秒） |

## 验收示例（curl）

```bash
# 静态管理页面
curl -i http://127.0.0.1:8080/

# 设备状态
curl -s http://127.0.0.1:8080/api/status | python3 -m json.tool

# 表单提交配置（持久化到 gwadmin-config.json）
curl -i -X POST http://127.0.0.1:8080/api/config \
  -d 'sampling_interval_ms=250&alarm_threshold=66.5'

# JSON 提交配置
curl -i -X POST http://127.0.0.1:8080/api/config \
  -H 'Content-Type: application/json' -d '{"device_name": "line-3-gw"}'

# 查询生效配置
curl -s http://127.0.0.1:8080/api/config

# 错误响应
curl -i http://127.0.0.1:8080/nope                 # 404
curl -i -X DELETE http://127.0.0.1:8080/api/status # 405 + Allow 头
curl -i 'http://127.0.0.1:8080/../../etc/passwd'   # 404（目录遍历防护）
curl -i -H "X-Big: $(head -c 9000 /dev/zero | tr '\0' A)" \
  http://127.0.0.1:8080/                           # 400（超长头部）

# Keep-Alive：同一连接连续两个请求
curl -v http://127.0.0.1:8080/api/status http://127.0.0.1:8080/api/config

# 并发：12 个并行请求
seq 12 | xargs -P 12 -I{} curl -s -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:8080/api/status
```

## 测试

```bash
python3 -m pytest tests/ -v
```

测试覆盖：请求解析边界（非法请求行、缺失 Host、超大头部、Content-Length
不匹配、畸形字符）、路由与方法分发（405/Allow）、表单与 JSON 体解析、
`/api/status` 与 `/api/config` 业务链路（含持久化与重启恢复）、静态文件
（MIME/404/默认页/目录遍历防护）、Keep-Alive 连接复用与流水线、并发多连接
（10+ 不崩溃不串包）、错误状态码页面、500 兜底不泄漏堆栈、空闲超时与干净
关机。集成测试默认在**临时端口启动真实服务**；在禁止 `bind()` 的沙箱环境中
自动降级为 socketpair 传输（仍执行同一套服务器连接处理代码路径）。

## 代码结构

```
gwadmin/
  __main__.py   # CLI 启动器（--host/--port/--root/--workers/...）
  app.py        # 应用装配：API 路由、配置校验与持久化
  http.py       # 自实现 HTTP/1.1 协议层（请求解析 / 响应序列化）
  router.py     # 路由注册与分发、路径参数、中间件钩子
  server.py     # 多线程 socket 服务器、Keep-Alive、访问日志、干净关机
  static.py     # 静态文件服务、MIME 表、目录遍历防护
tests/          # pytest 测试套件（单元 + 真实服务集成）
www/            # 演示管理页面（index.html / style.css / app.js）
```

## 安全硬约束

- 目录遍历：任何解码后含 `..` 段的路径一律 404，且规范化后的绝对路径必须
  位于 `--root` 之内
- 超长请求：请求行 + 头部 > 8KB → 400；请求体 > 16MB → 413
- 畸形请求：只返回 400 或关闭连接，进程不退出
- 500 兜底：不向客户端泄漏堆栈或内部细节
