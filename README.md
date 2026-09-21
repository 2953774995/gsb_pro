# gwadmin — 工厂边缘网关本地管理 Agent

`gwadmin` 是一个面向 ARM 工控机/车间局域网的本地 HTTP 管理服务。运行时代码只使用 **Python 标准库** 和原生 `socket` / `threading`，没有使用 `http.server`、`BaseHTTPRequestHandler` 或任何第三方 Web 框架；测试仅依赖 `pytest`。

## 功能清单

- 手写 HTTP/1.0、HTTP/1.1 协议解析与响应序列化
  - 请求行、大小写不敏感请求头、query string、固定长度请求体
  - 请求行 + 请求头默认最大 8KB，超限返回 `400`
  - 非法请求行、坏版本、非法头、重复关键头、非法 `Content-Length` 返回 `400`
  - 请求体超过上限返回 `413`，未按长度读完整返回 `400`
  - HTTP/1.1 默认 Keep-Alive，支持 `Connection: close`；HTTP/1.0 默认关闭
  - 响应包含 `Content-Type`、`Content-Length`、`Connection`、`Server`、`Date`
  - `HEAD` 不返回响应体，但保留与 GET 相同的 `Content-Length`
- 路由 API
  - `GET` / `POST` / `PUT` / `DELETE`（另支持 `HEAD`、`OPTIONS`、`PATCH` 注册）
  - 支持 `/devices/:id` 路径参数
  - 未命中为 `404`，路径存在但方法不匹配为 `405` 并返回 `Allow`
  - handler 统一签名：`handler(request) -> (status, headers, body)`，body 支持 `bytes` / `str` / `None`
  - 提供可测试的请求前、响应后中间件钩子
- 静态文件
  - `--root` 指定管理页面目录
  - 常见扩展名 MIME 表
  - 目录 `/` 返回 `index.html`，无 index 返回 `403`
  - 非斜杠目录请求 301 到斜杠路径
  - 严格拒绝 `..`、`%2e%2e`、双重编码/解码后的目录穿越
  - 使用 `realpath` 包含校验并拒绝静态文件符号链接
- 管理 API
  - `GET /api/status`：版本、运行时长、工作线程数、已处理请求数、主机信息
  - `GET /api/config`：读取当前配置
  - `POST/PUT /api/config`：接收 JSON 或 `application/x-www-form-urlencoded`
  - 配置字段：`sample_interval`、`alarm_threshold`、`device_name`、`enabled`
  - 原子写入本地 JSON，非法值返回 `400` 和错误原因
- 并发与稳定性
  - 有界连接线程处理多连接，默认 16 个 worker（信号量限流）
  - 空闲连接默认 30 秒超时
  - 每个连接和每个请求都有异常兜底，未捕获错误仅返回通用 `500` 页面
  - SIGINT/SIGTERM 停止接收新连接，关闭监听 socket 和现有连接
- 访问日志输出到 stdout：时间、方法、路径、状态码、耗时毫秒

## 目录结构

```text
gwadmin/             运行时代码
  protocol.py        手写 HTTP 请求解析/响应序列化
  server.py          socket 监听、连接线程/限流、连接生命周期
  router.py          路由与路径参数
  app.py             应用组装、中间件、统一错误处理
  static_files.py    静态文件和目录穿越防护
  config_store.py    配置校验与 JSON 持久化
  forms.py           表单和 JSON 请求体解析
  cli.py             命令行参数
static/              默认管理页面
tests/               pytest 测试
bin/gwadmin          免安装启动脚本
```

## 快速开始

在项目根目录执行：

```bash
python3 -m gwadmin --host 0.0.0.0 --port 8080 --root static --workers 16
```

也可以使用启动脚本：

```bash
./bin/gwadmin --host 0.0.0.0 --port 8080 --root static --workers 16
```

参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--host` | `0.0.0.0` | 监听地址 |
| `--port` | `8080` | 监听端口 |
| `--root` | `static` | 静态资源目录 |
| `--workers` | `16` | 连接工作线程数 |
| `--config` | `data/config.json` | 配置持久化文件 |
| `--idle-timeout` | `30` | Keep-Alive 空闲超时秒数 |
| `--header-limit` | `8192` | 请求行 + 头部大小上限 |
| `--body-limit` | `1048576` | 请求体大小上限 |

## curl 验收示例

启动后：

```bash
# 静态首页
curl -i http://127.0.0.1:8080/

# 设备状态
curl -s http://127.0.0.1:8080/api/status

# 当前配置
curl -s http://127.0.0.1:8080/api/config

# 表单提交
curl -i -X POST http://127.0.0.1:8080/api/config \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data 'sample_interval=2000&alarm_threshold=90'

# JSON 提交
curl -i -X POST http://127.0.0.1:8080/api/config \
  -H 'Content-Type: application/json' \
  --data '{"sample_interval":1500,"alarm_threshold":88.5}'

# 方法不匹配，带 Allow
curl -i -X DELETE http://127.0.0.1:8080/api/status

# 不存在路径
curl -i http://127.0.0.1:8080/not-found

# 目录穿越会被拒绝
curl -i --path-as-is http://127.0.0.1:8080/../etc/passwd
```

## 路由扩展

```python
from gwadmin.app import Application

app = Application(root="static", config_path="data/config.json")

@app.before_request
def auth(request):
    # 返回 None 继续执行；返回三元组则短路
    return None

@app.after_response
def add_header(request, status, headers, body):
    headers["X-Edge-Gateway"] = "gwadmin"
    return status, headers, body

app.router.get("/devices/:id", lambda request: (
    200,
    {"Content-Type": "text/plain; charset=utf-8"},
    request.params["id"],
))
```

## 安全说明

- 请求头按总字节数在读取过程中即时截断，避免超大头耗尽内存。
- 不支持 `Transfer-Encoding`/chunked；管理端只接受明确且合法的 `Content-Length`。
- 静态路径先拒绝显式 `..` 段，再做 `realpath` 根目录包含校验，防止 `%2e%2e`、解码穿越和符号链接逃逸。
- 重复的 `Host` / `Content-Length` 被拒绝，避免请求走私类歧义。
- 应用异常不会把 Python 堆栈返回给浏览器；详细异常仅写服务端日志。
- 收到 SIGINT/SIGTERM 后停止 accept，关闭监听 socket，并关闭当前客户端连接。

## 运行测试

```bash
python3 -m pytest tests/ -v
```

测试覆盖协议边界、405/Allow、路径参数、表单和 JSON、状态/配置业务、静态 MIME/默认页/404/目录穿越、HEAD、Keep-Alive 复用、16 个并发连接、错误页面和 CLI 参数。

> 测试默认尝试绑定临时 TCP 端口启动真实服务；如果某个强沙箱环境完全禁止 `bind()`，测试夹具会自动使用 `socketpair` 走同一套服务端连接处理代码，以便在受限 CI 中仍可验证协议与业务逻辑。正常 Linux/macOS/ARM Linux 环境会使用真实临时端口。

## 依赖

- 运行：Python 3.9+ 标准库
- 测试：`pytest`
