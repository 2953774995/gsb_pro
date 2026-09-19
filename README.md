# miniweb

一个从零实现的迷你 HTTP/1.1 Web 服务器。**只使用 Python 标准库**
（`socket` / `threading` / `argparse` 等），不使用 `http.server`、
`BaseHTTPRequestHandler` 等任何现成 HTTP 实现，被测代码零第三方依赖
（测试框架 pytest 除外）。

## 功能

- **手写协议解析**：请求行 / 请求头（大小写不敏感、重复头逗号合并）/
  按 `Content-Length` 精确读取请求体；请求行与头部默认上限 8KB，
  超限返回 400；query string 解析为参数映射
- **手写响应序列化**：状态行 + 至少五项响应头（`Content-Type`、
  `Content-Length`、`Connection`、`Server`、`Date`）；覆盖
  200/301/302/400/403/404/405/413/500 并提供默认错误页；
  HEAD 只返回头部但 `Content-Length` 正确
- **Keep-Alive**：HTTP/1.1 默认保持连接，`Connection: close` 与
  HTTP/1.0 语义正确；连接空闲超时（默认 30s）自动关闭
- **路由**：`Router` 支持 GET/POST/PUT/DELETE 与 `/users/:id` 路径参数；
  未注册路径 404，方法不匹配 405 且带 `Allow` 头；处理器签名
  `handler(request) -> (status, headers, body)`，body 支持
  bytes/str/None；支持请求前 / 响应后中间件钩子
- **静态文件**：`--root` 指定目录，内置常见 MIME 表，目录请求返回
  `index.html` 否则 403；路径规范化后强制限制在根目录内，
  任何 `../` 或编码穿越（`%2e%2e`、`..%2f` 等）一律 404
- **并发**：每连接一线程 + 信号量限流（`--workers`）；畸形请求只返回
  400 或关闭连接，绝不打挂进程；未捕获异常统一兜底为 500
  （不泄漏堆栈）；SIGINT 干净关机
- **应用层辅助**：`request.form`（urlencoded：`+` 转空格、百分号解码、
  重复键聚合为列表）、`request.json`（非法 JSON 返回 400）
- **访问日志**：时间、方法、路径、状态码、耗时毫秒，输出到标准输出

## 快速开始

```bash
# 启动（静态目录 + 内置演示路由）
python3 -m miniweb --host 127.0.0.1 --port 8000 --root ./www --workers 32

curl http://127.0.0.1:8000/                 # 静态 index.html 或演示页
curl http://127.0.0.1:8000/api/hello        # 演示路由
curl -X POST -d 'a=1&a=2' http://127.0.0.1:8000/api/echo
curl http://127.0.0.1:8000/nope             # 404
curl -X POST http://127.0.0.1:8000/api/hello # 405 + Allow
curl http://127.0.0.1:8000/../etc/passwd    # 404（目录穿越防护）
```

按 `Ctrl-C`（SIGINT）干净关机：停止接受新连接并关闭现有连接。

## 作为库使用

```python
from miniweb import Application, HTTPServer

app = Application(static_root="./www")

@app.get("/users/:id")
def show_user(request):
    return 200, [("Content-Type", "text/plain")], "user " + request.path_params["id"]

@app.post("/submit")
def submit(request):
    form = request.form            # {'a': ['1', '2'], ...}
    return 200, [], "got %r" % form

@app.before_request
def auth(request):                 # 返回响应元组可短路
    return None

@app.after_response
def add_header(request, response):
    status, headers, body = response
    return status, headers + [("X-App", "demo")], body

server = HTTPServer("127.0.0.1", 8000, app, workers=32, idle_timeout=30)
server.serve_forever()             # server.shutdown() 干净停止
```

## 项目结构

```
miniweb/
  request.py      请求解析（请求行/头部/正文，8KB 上限，Content-Length 校验）
  response.py     响应序列化、状态码表、默认错误页
  router.py       路由与路径参数、404/405(Allow)
  staticfiles.py  静态文件、MIME 表、目录遍历防护
  app.py          应用装配：路由 + 静态 + 中间件 + 500 兜底
  server.py       多线程服务器：accept 循环、Keep-Alive、空闲超时、干净关机
  cli.py          命令行启动器（--host/--port/--root/--workers）
tests/            pytest 套件（真实临时端口起服务）
```

## 测试

```bash
python3 -m pytest tests/ -v
```

覆盖：请求解析边界（非法请求行、缺失 Host、超大头部、Content-Length
不匹配、畸形字符）、路由与方法分发（含 405/Allow）、POST 表单与 JSON、
静态文件（MIME/404/默认页/目录穿越）、Keep-Alive 连接复用、
16 路并发不串包、错误状态码页面等 75 个用例。

> 注：测试默认在临时端口启动真实 TCP 服务；在禁止 bind 的受限沙箱中，
> conftest 会自动降级为 socketpair 传输，运行的仍是同一份服务器代码。
