# miniweb

`miniweb` 是一个教学用途的 HTTP/1.1 Web 服务器。它只使用 Python 标准库，直接基于 `socket` 和 `threading` 实现协议解析、响应序列化、路由、静态文件服务与多线程并发；没有使用 `http.server`、`BaseHTTPRequestHandler` 或任何第三方运行时依赖。

## 功能特性

- 手写 HTTP/1.1 请求解析：请求行、请求头、`Content-Length` 请求体、query string。
- 请求头键大小写不敏感；重复请求头按 `RFC 7230` 风格合并为逗号分隔值。
- 请求行与请求头默认上限 8192 字节；请求体默认上限 16 MiB。
- 支持 `GET`、`POST`、`PUT`、`DELETE`，并自动用 `GET` 处理器响应 `HEAD`。
- 支持 `/users/:id` 路径参数、404、405 与 `Allow` 响应头。
- Handler 返回值统一为 `(status, headers, body)`，`body` 支持 `bytes`、`str`、`None`。
- 支持 `before_request` / `after_request` 中间件。
- 支持静态目录、`index.html`、常见扩展名 MIME、目录无索引时 403。
- 严格防护 `..`、反斜杠、百分号编码与双重编码目录穿越。
- 解析 `application/x-www-form-urlencoded` 表单，支持 `+`、百分号解码、重复键聚合。
- 解析 `application/json` 请求体，非法 JSON 返回 400。
- 覆盖 `200/301/302/400/403/404/405/413/500` 等状态码和默认 HTML 错误页。
- `HEAD` 响应不发送消息体，但 `Content-Length` 仍表示对应 GET 资源长度。
- HTTP/1.1 默认 Keep-Alive，HTTP/1.0 默认关闭，`Connection: close` 正确关闭。
- 线程池处理多连接；默认 30 秒空闲超时；畸形请求不会打挂进程。
- 访问日志输出到标准输出；未捕获异常统一转换为不带堆栈的 500 页面。
- 收到 `SIGINT`/`SIGTERM` 后停止接受新连接并关闭现有连接。

## 目录结构

```text
miniweb/
├── __init__.py          # 公共 API
├── __main__.py          # python -m miniweb 启动入口
├── cli.py               # 安装后的 miniweb 命令入口
├── application.py       # 应用、中间件、统一异常处理
├── datastructures.py    # 大小写不敏感的请求头容器
├── demo.py              # CLI 默认演示路由
├── errors.py            # HTTP 异常
├── parser.py            # HTTP/1.1 请求解析
├── request.py           # Request、query/form/json 解析
├── response.py          # Response、状态行/响应头序列化、错误页
├── router.py            # 路由与路径参数
├── server.py            # socket、线程池、Keep-Alive、日志和关机
└── static.py            # 静态文件、MIME 与目录穿越防护
tests/                   # pytest 真实临时端口集成测试
bin/miniweb              # 免安装启动脚本
```

## 快速开始

要求 Python 3.8+。不需要创建虚拟环境也可以运行；除 pytest 外无需安装任何包。

```bash
# 使用临时静态目录启动
mkdir -p web
printf '<h1>Hello miniweb</h1>' > web/index.html

python3 -m miniweb --host 127.0.0.1 --port 8000 --root web --workers 16
```

也可以使用仓库中的启动脚本：

```bash
./bin/miniweb --host 127.0.0.1 --port 8000 --root web
```

可选安装为命令：

```bash
python3 -m pip install -e .
miniweb --host 127.0.0.1 --port 8000 --root web
```

## 命令行参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--host` | `127.0.0.1` | 监听地址 |
| `--port` | `8000` | 监听端口，`0` 表示由系统分配端口 |
| `--root` | 无 | 静态文件根目录；不提供时使用演示首页 |
| `--workers` | `16` | 工作线程数 |
| `--timeout` | `30` | 单连接空闲超时秒数 |

启动时输出监听地址：

```text
miniweb listening on http://127.0.0.1:8000
```

访问日志示例：

```text
2026-09-20T10:15:01.123 127.0.0.1 GET /style.css 200 0.42ms
2026-09-20T10:15:02.002 127.0.0.1 POST /echo/form 200 0.58ms
```

## curl 验收示例

启动：

```bash
mkdir -p web
printf 'body { color: red; }' > web/style.css
python3 -m miniweb --host 127.0.0.1 --port 8000 --root web
```

静态文件：

```bash
curl -i http://127.0.0.1:8000/style.css
curl -i http://127.0.0.1:8000/
```

动态路由：

```bash
curl -i 'http://127.0.0.1:8000/hello?name=Ada'
curl -i http://127.0.0.1:8000/users/42
```

表单提交：

```bash
curl -i -X POST http://127.0.0.1:8000/echo/form \
  --data 'name=Jane+Doe&city=S%26F&tag=a&tag=b'
```

JSON：

```bash
curl -i -X POST http://127.0.0.1:8000/echo/json \
  -H 'Content-Type: application/json' \
  -d '{"name":"Ada","roles":["admin","user"]}'
```

错误状态码：

```bash
curl -i http://127.0.0.1:8000/missing
curl -i -X DELETE http://127.0.0.1:8000/hello
curl -i http://127.0.0.1:8000/boom
```

目录穿越会返回 404：

```bash
curl -i --path-as-is 'http://127.0.0.1:8000/../etc/passwd'
curl -i --path-as-is 'http://127.0.0.1:8000/%2e%2e/etc/passwd'
curl -i --path-as-is 'http://127.0.0.1:8000/%252e%252e/etc/passwd'
```

## 编程方式使用

```python
from miniweb import Application, Router, Server

router = Router()

@router.get("/hello")
def hello(request):
    name = request.query.get("name", "world")
    return 200, {"Content-Type": "text/plain; charset=utf-8"}, f"hello {name}"

@router.post("/users")
def create_user(request):
    data = request.json  # 非法 JSON 会由应用层转成 400
    return 201, {"Content-Type": "application/json"}, data

@router.get("/users/:id")
def get_user(request):
    user_id = request.params["id"]
    return 200, {}, f"user {user_id}"

app = Application(router=router, static_root="web")

@app.before_request
def before(request):
    request.started_by = "miniweb"

@app.after_request
def after(request, response):
    response.headers["x-miniweb"] = ("X-Miniweb", "yes")

server = Server(app, host="127.0.0.1", port=8000, workers=16)
server.serve_forever()
```

### Request API

- `request.method`：HTTP 方法。
- `request.raw_path`：未解码路径，不含 query。
- `request.path`：百分号解码后的路径。
- `request.query_string`：原始 query string。
- `request.query`：查询参数；单键为 `str`，重复键聚合为 `list[str]`。
- `request.params`：路由路径参数。
- `request.headers`：大小写不敏感请求头。
- `request.body`：原始 `bytes` 请求体。
- `request.form`：解析 `application/x-www-form-urlencoded`；重复键聚合为列表。
- `request.json`：仅在 JSON content-type 下解析，失败抛出会转换为 400 的异常。

### Handler 返回值

```python
return 200, {"Content-Type": "text/plain; charset=utf-8"}, "hello"
return 404, {}, None
return 200, {"Content-Type": "application/json"}, b'{"ok":true}'
```

也可以返回 `miniweb.Response` 或 `redirect(location, status=302)`。

## 协议与安全细节

- HTTP/1.1 必须携带 `Host`，否则返回 400。
- 仅支持源形式请求目标，例如 `/path?a=1`；不支持绝对 URI 请求目标。
- 不支持 chunked transfer coding，收到 `Transfer-Encoding` 返回 400 并关闭连接。
- `Content-Length` 非数字、负数或声明长度大于实际请求体时返回 400。
- 请求行或头部超过 8192 字节返回 400。
- 请求体大于 16 MiB 返回 413 并关闭连接，避免服务器继续读取超大 body。
- 静态文件先进行路径片段检查，再重复百分号解码，最后 `Path.resolve()` 并要求结果仍在根目录内。
- 包含字面 `..`、任何 `..` 片段、反斜杠、编码分隔符或双重编码穿越尝试的静态路径返回 404。
- 目录存在但没有 `index.html` 时返回 403。
- 用户处理器异常不会向客户端发送堆栈，只返回统一 500 页面；异常详情写服务端日志。
- 响应头值禁止 CR/LF，防止响应拆分。

## 测试

测试通过 pytest 启动真实 socket 服务并使用系统分配的临时端口，不是模拟请求。

```bash
python3 -m pytest tests/ -v
```

覆盖内容包括：

- 非法请求行、坏版本号、缺失 Host、畸形头部、畸形控制字符。
- 8KB 头部限制、非法 `Content-Length`、请求体长度不匹配、413。
- 路由、路径参数、query 重复键、405 与 `Allow`、HEAD。
- 表单和 JSON 请求体解析。
- MIME、默认首页、403/404、各种目录穿越编码。
- Keep-Alive 同连接连续请求、`Connection: close`、HTTP/1.0 语义。
- 20 个并发连接响应不串包。
- 默认错误页和 500 不泄漏堆栈。
- CLI 子进程启动、真实请求和 `SIGINT` 干净关机。

## 设计边界

为了保持代码小巧、可审计，当前版本不包含：

- chunked request body；
- TLS/HTTPS；
- 虚拟主机路由；
- 自动 OPTIONS/CORS；
- 条件请求和压缩传输；
- 异步 I/O。

这些都不影响 PRD 中要求的 HTTP/1.1 基础服务器、静态文件、表单/JSON、并发、错误处理和关机能力。
