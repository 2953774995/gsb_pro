# tinytpl

一个从零实现的迷你模板引擎，**只使用 Python 标准库**（测试框架 pytest 除外）。
支持变量输出、HTML 转义、条件、循环、表达式求值、模板继承与包含。

## 功能一览

- 变量输出：`{{ name }}`（自动 HTML 转义）、`{{ name | raw }}`（不转义）
- 点号取值：`{{ user.name }}`、`{{ items.0 }}`、`{{ users.1.name }}`
- 条件：`{% if %}` / `{% elif %}` / `{% else %}` / `{% endif %}`
- 循环：`{% for x in items %}` ... `{% endfor %}`，循环内可用
  `loop.index`（从 1 开始）、`loop.index0`、`loop.first`、`loop.last`、`loop.length`
- 注释：`{# 注释内容 #}`（渲染时被完全移除）
- 表达式：字符串/数字/布尔/None 字面量、比较（`== != < <= > >=`）、
  逻辑（`and or not`，短路求值）、算术（`+ - * / // %`）、一元负号、括号
- 模板继承：`{% extends "base.html" %}` + `{% block name %}...{% endblock %}`，
  支持多级继承，子模板覆盖父模板的同名 block
- 模板包含：`{% include "partial.html" %}`（被包含模板能看到当前上下文变量）
- 过滤器：`raw`、`escape`（别名 `e`）、`upper`、`lower`、`length`，
  可通过 `Environment(filters={...})` 注册自定义过滤器

## 安装与运行

无第三方依赖，直接在项目根目录使用即可。也可以安装为包以获得
`tinytpl-cli` 命令：

```bash
pip install .          # 可选，提供 tinytpl-cli 命令
```

### Python API

```python
from tinytpl import Template, Environment, DictLoader, FileSystemLoader

# 方式一：直接编译字符串
print(Template("Hello {{ name }}!").render(name="world"))

# 方式二：通过 Environment + loader 解析 extends/include
env = Environment(loader=FileSystemLoader("templates"))
print(env.get_template("page.html").render({"name": "world"}))

# 字典 loader
env = Environment(DictLoader({"base.html": "...", "page.html": "..."}))

# 严格模式：缺失变量抛 TplError（默认渲染为空字符串）
Template("{{ missing }}", strict=True).render()        # 抛 TplError
env = Environment(loader=..., strict=True)
```

### 命令行工具

```bash
tinytpl-cli template.html data.json            # 安装后
python3 -m tinytpl.cli template.html data.json # 免安装
python3 -m tinytpl template.html data.json     # 同上

# extends/include 相对模板所在目录解析；--strict 开启严格模式
python3 -m tinytpl.cli examples/templates/catalog.html examples/data.json
```

退出码：`0` 成功；`1` 模板语法/引用错误；`2` 数据文件读取或 JSON 解析失败。

## 语法与语义

### 转义

`{{ ... }}` 输出默认对 `< > & " '` 做 HTML 转义
（`&` → `&amp;`，`<` → `&lt;`，`>` → `&gt;`，`"` → `&quot;`，`'` → `&#x27;`）。
`{{ x | raw }}` 跳过转义，原样输出。`None` 渲染为空字符串。

### 变量缺失

- 默认模式：缺失变量渲染为空字符串，在条件中视为假值，for 循环视为空序列。
- 严格模式（`strict=True`）：任何对缺失变量的使用都抛出 `TplError`。

### 作用域

采用词法作用域：for 循环的循环变量与 `loop` 辅助变量只存在于循环体内，
不会泄漏到块外；嵌套循环中内层变量遮蔽外层同名变量，退出后恢复。

### 继承语义

- 子模板用 `{% extends "base.html" %}` 声明父模板（模板名也可以是变量表达式）。
- 渲染时输出父模板骨架，父模板中的 `{% block %}` 被子模板同名 block 覆盖；
  未覆盖的 block 使用父模板默认内容。支持多级继承（孙 → 子 → 基）。
- 同一模板中 block 名称重复会抛出 `TplError`。
- 循环继承 / 循环包含会被检测并抛出 `TplError`。

## 错误处理

所有语法错误（未闭合标签、未知标签、`endif`/`endfor` 不匹配、block 重名等）
与引用错误（模板不存在）都抛出自定义异常 `tinytpl.TplError`
（`TemplateNotFound` 是其子类），错误信息包含模板名与行号（可用时）。

## 项目结构

```
tinytpl/
  __init__.py      # 公共 API 导出
  errors.py        # TplError / TemplateNotFound
  escape.py        # HTML 转义与 SafeString
  tokenizer.py     # 将模板源码切分为 text/var/tag token
  expression.py    # 表达式词法分析、递归下降解析与求值
  parser.py        # 语句级解析（if/for/block/extends/include），生成 AST
  nodes.py         # AST 节点、渲染上下文（作用域栈）、Undefined
  loader.py        # DictLoader / FileSystemLoader
  environment.py   # Environment 与 Template（渲染入口、继承解析）
  cli.py           # tinytpl-cli 命令行工具
tests/             # pytest 测试套件
examples/          # extends + block + include + for + if 多文件示例
```

## 运行测试

```bash
python3 -m pytest tests/ -v
```

## 示例

```bash
python3 -m tinytpl.cli examples/templates/catalog.html examples/data.json
```

渲染一个「基模板 + 子模板覆盖 block + include 部分模板 + for 循环 +
if 条件」的完整商品目录页面（见 `examples/`）。
