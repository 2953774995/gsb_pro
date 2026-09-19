# tinytpl

一个**仅依赖 Python 标准库**的迷你模板引擎，支持变量输出、条件、循环、
表达式求值、模板继承（extends/block）与包含（include）。
被测代码零第三方依赖（仅测试使用 pytest）。

## 安装 / 运行

无需安装即可直接使用（要求 Python 3.8+）：

```bash
# 作为库
python3 -c "import tinytpl; print(tinytpl.Template('Hi {{ name }}').render(name='World'))"

# 命令行渲染（两种方式等价）
python3 -m tinytpl examples/templates/user_list.html examples/data.json
# 或安装后使用 tinytpl-cli
pip install .
tinytpl-cli examples/templates/user_list.html examples/data.json
```

CLI 用法：`tinytpl-cli <模板文件> <JSON数据文件> [--strict]`，
模板中的 `extends` / `include` 相对模板文件所在目录解析，
渲染结果输出到 stdout；模板错误退出码 1，数据文件错误退出码 2。

## 模板语法

所有语法标记使用 `{{ ... }}` / `{% ... %}` / `{# ... #}`。

### 变量输出与转义

```
{{ name }}          → HTML 转义输出：< > & " ' 分别转义为
                      &lt; &gt; &amp; &quot; &#x27;
{{ name | raw }}    → 不转义，原样输出
{{ user.name }}     → 点号取值（dict 键 / 对象属性）
{{ items.0 }}       → 列表/元组下标
{# 注释 #}          → 注释，不产生任何输出
```

### 条件

```
{% if cond %} ... {% elif cond2 %} ... {% else %} ... {% endif %}
```

### 循环

```
{% for x in items %}
  {{ loop.index }}   ← 1 起始的序号（另有 loop.index0）
  {{ loop.first }}   ← 是否第一轮
  {{ loop.last }}    ← 是否最后一轮
  {{ loop.length }}  ← 长度
{% endfor %}
```

循环变量与 `loop` 只在循环体内可见（词法作用域），不会泄漏到块外；
嵌套循环中内层 `loop` 遮蔽外层，退出后恢复。

### 表达式

`{{ }}` 与 `{% if %}` / `{% for %}` 中支持：

- 字面量：字符串（`'a'` / `"a"`）、数字（`1`、`2.5`）、`True` / `False` / `None`
- 比较：`== != < <= > >=`（支持链式：`1 < x < 10`）
- 逻辑：`and` `or` `not`（短路求值，返回操作数值，同 Python）
- 算术：`+ - * / // %`、一元 `-`/`+`
- 括号：`(...)`

### 模板继承与包含

```
{# base.html #}
<title>{% block title %}默认标题{% endblock %}</title>
<body>{% block content %}{% endblock %}</body>

{# page.html #}
{% extends "base.html" %}
{% block title %}我的页面{% endblock %}
{% block content %}你好 {{ name }}{% endblock %}

{% include "footer.html" %}   ← 包含并渲染另一个模板（可见当前上下文）
```

语义：

- `extends` 必须是模板的第一个标签（之前只允许空白），且只能在顶层出现一次
- 子模板用同名 `block` 覆盖父模板内容；未覆盖的 block 使用父模板默认内容
- 支持多级继承（A extends B extends C），最下层子模板的覆盖优先
- 继承时子模板 block 之外的内容不输出
- 同一模板内 block 名重复会抛 `TplError`
- `endblock` 可带名字（`{% endblock title %}`），不匹配会报错

## Python API

```python
from tinytpl import Template, Environment, DictLoader, FileSystemLoader, TplError

# 直接渲染字符串
Template("Hello {{ name }}!").render(name="World")

# 通过 Environment + loader 渲染命名模板（支持 extends/include，带缓存）
env = Environment(FileSystemLoader("templates/"))     # 或 DictLoader({"a": "..."})
output = env.get_template("page.html").render({"name": "World"})

# 严格模式：缺失变量抛 TplError（默认渲染为空字符串）
env = Environment(FileSystemLoader("templates/"), strict=True)
Template("{{ oops }}", strict=True).render()          # → TplError
```

## 渲染语义

- **缺失变量**：默认渲染为空字符串（在条件中为假、在循环中为空迭代）；
  `strict=True` 时抛 `TplError`
- **作用域**：`for` / `if` 块为词法作用域，块内变量查找沿作用域链向外，
  循环变量不泄漏到块外
- **转义**：默认对 `{{ }}` 输出做 HTML 转义；`| raw` 过滤器跳过转义
- **错误**：所有语法错误（未闭合标签、未知标签、endif 不匹配等）、
  模板不存在、block 名冲突、表达式求值错误都抛出自定义异常
  `tinytpl.TplError`，消息中尽量带行号

## 代码结构

```
tinytpl/
  tokenizer.py    源码 → token 流（text/var/tag，注释丢弃，检测未闭合标签）
  expr.py         表达式词法 + 递归下降解析 + 求值（比较/逻辑/算术/括号）
  parser.py       token 流 → 模板 AST，收集 extends/blocks，语法错误检查
  nodes.py        AST 节点（Text/Var/If/For/Block/Extends/Include）的渲染
  renderer.py     渲染上下文：作用域链、Undefined、loop 对象
  loader.py       DictLoader / FileSystemLoader
  environment.py  Environment：loader + 配置 + 模板缓存
  template.py     Template：编译 + render 入口，驱动继承链渲染
  escape.py       HTML 转义
  errors.py       TplError
  cli.py          tinytpl-cli 命令行工具
tests/            pytest 测试（106 个用例）
examples/         多文件演示场景（extends + block + include + for + if）
```

## 运行测试

```bash
python3 -m pytest tests/ -v
```

## 演示

```bash
python3 -m tinytpl examples/templates/user_list.html examples/data.json
```

渲染一个使用 `extends`/`block`/`include` + `for` + `if` 的完整页面，
输出中包含正确的 HTML 转义（如 `Carol <script>` → `Carol &lt;script&gt;`）。
