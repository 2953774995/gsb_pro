# mdsite

`mdsite` 是一个教学/自用友好的静态站点生成器：递归扫描目录中的 Markdown 文件，生成可以直接部署到任意静态服务器的 HTML 站点。

除开发测试使用 `pytest` 外，运行时只依赖 **Python 标准库**。Markdown 解析器、代码高亮器和模板引擎均在项目内手写，没有使用 `markdown`、`mistune`、`jinja2` 等库。

## 功能清单

### Markdown 语法

- 标题：`#` 到 `######`
- 段落、粗体 `**text**`、斜体 `*text*`
- 行内代码：`` `code` ``
- 围栏代码块：三个反引号或三个波浪线，支持语言标注，例如 <code>```python</code>
- 引用块：`> quote`，引用内可继续放段落、列表等块级内容
- 无序列表：`-`、`*`、`+`
- 有序列表：`1.` 或 `1)`
- 两级及多级嵌套列表；2 空格和 4 空格缩进混用时也不会崩
- 链接：`[text](url)`，支持空文本和 URL 中的嵌套括号
- 图片：`![alt](src)`
- 水平线：`---`（也支持 `***`、`___`）
- 表格：管道符表格，表头下使用 `---` 分隔行；支持 `:---`、`:---:`、`---:` 对齐
- 表格内可用 `\|` 表示字面量竖线
- 行内 HTML 原样透传；常见块级 HTML（如 `<div>`、`<section>`、HTML 注释）原样输出
- 代码块和行内代码中的 `<`、`>`、`&` 都会转义；代码块内部不会解析 `**bold**` 等 Markdown

### 站点能力

- 递归扫描输入目录中的 `.md` 文件
- 按输入目录结构生成对应 `.html`
- 每页自动生成右侧 TOC，仅提取 `h2` / `h3`
- 锚点由标题文本 slug 化生成：小写、空白转连字符、去标点；中文等 Unicode 字符保留
- 同页重复标题自动追加 `-1`、`-2`
- Python 代码做基于关键词、字符串、注释、数字、装饰器规则的简单高亮
- 内置统一页面模板：导航栏、内容区、右侧目录、页脚
- 内置模板引擎支持：
  - 变量：`{{ title }}`、`{{ page.title }}`
  - 条件：`{% if toc %} ... {% else %} ... {% endif %}`，支持 `not`
  - 循环：`{% for link in nav_links %} ... {% endfor %}`
- 内置 `default` 和 `dark` 两套 CSS，构建时都会复制到输出目录，并把当前主题复制为 `assets/style.css`
- 自动复制图片等非 Markdown 静态资源
- Markdown 页面中的相对 `*.md` 链接会自动改写为对应 `*.html`，锚点保留；块级 HTML 中的链接保持原样
- 没有 `index.md` 时自动生成目录首页

## 目录结构

```text
.
├── mdsite/
│   ├── cli.py          # build / serve 命令行
│   ├── builder.py      # 扫描、渲染、复制资源、套模板
│   ├── markdown.py     # 手写 Markdown 块级/行内解析器
│   ├── highlight.py    # 简易语法高亮
│   ├── template.py     # 简易模板引擎
│   ├── templates/
│   │   └── default.html
│   └── themes/
│       ├── default.css
│       └── dark.css
├── examples/docs/      # 可构建的示例文档
└── tests/              # pytest 测试
```

输入和输出示例：

```text
docs/
├── index.md
├── assets/logo.svg
└── guide/
    ├── getting-started.md
    └── syntax.md

site/
├── index.html
├── assets/
│   ├── logo.svg
│   ├── style.css
│   ├── default.css
│   └── dark.css
└── guide/
    ├── getting-started.html
    └── syntax.html
```

## 安装

在项目根目录执行：

```bash
python -m pip install -e .
```

也可以不安装，直接用模块方式运行：

```bash
python -m mdsite --help
```

需要 Python 3.8+。

## 构建站点

```bash
mdsite build <输入目录> <输出目录>
```

例如：

```bash
mdsite build examples/docs site
```

指定站点名和主题：

```bash
mdsite build examples/docs site --site-name "团队文档" --theme dark
```

可选主题：

- `default`：浅色主题（默认）
- `dark`：深色主题

每次构建都会把主题文件写入：

```text
site/assets/style.css      # 当前使用的主题
site/assets/default.css    # 浅色主题副本
site/assets/dark.css       # 深色主题副本
```

## 本地预览

先构建，再启动标准库 HTTP 服务：

```bash
mdsite serve site --port 8000
```

浏览器打开：

```text
http://127.0.0.1:8000/
```

## Markdown 示例

````markdown
# 页面标题

## 快速开始

正文里有 **粗体**、*斜体*、`code`、[链接](./other.md#章节)。

### 中文小节

- 第一项
  - 嵌套项
- 第二项

| 参数 | 说明 |
| --- | --- |
| `a \| b` | 字面量竖线 |

```python
# Python 注释
def hello(name="World"):
    print("<hi>", name)
```
````

## 错误处理

常见错误会输出单行中文提示并返回非零退出码，不直接把 traceback 糊到用户脸上，例如：

- 输入目录不存在
- 输入路径是文件而不是目录
- 主题不存在
- Markdown 文件不是 UTF-8
- 文件或目录因权限问题无法读取
- 输出文件无法写入

## 运行测试

```bash
pytest
```

测试覆盖：

- 所有标题层级、段落、粗体、斜体、行内代码
- 代码块语言类名、特殊字符转义、代码块内不做行内解析
- 引用块
- 有序/无序、嵌套和不规则缩进列表
- 链接和图片边界
- 水平线、表格和转义竖线
- 行内/块级 HTML 透传
- 中文 slug 与重复锚点
- Python 语法高亮
- 模板变量、if/else、for 和错误语法
- 端到端目录构建、TOC 跳转、相对链接、资源和主题复制、无占位符残留
- CLI 友好报错和 serve 参数处理
