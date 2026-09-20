# mdsite

自用的静态站点生成器：把一个目录里的 Markdown 文件全部转成能直接部署的 HTML 站点。

**零第三方依赖**——Markdown 解析器、模板引擎、代码高亮器全部手写，只用 Python 标准库（测试用 pytest）。Python 3.8+。

## 快速上手

```bash
# 构建：递归扫描 docs/ 下的 .md，输出到 site/
python -m mdsite build docs/ site/

# 换主题（内置 default / dark 两套）
python -m mdsite build docs/ site/ --theme dark

# 本地预览
python -m mdsite serve site/ --port 8000
# 打开 http://127.0.0.1:8000/
```

仓库里有一份示例文档，可以直接试：

```bash
python -m mdsite build examples/docs /tmp/site
python -m mdsite serve /tmp/site
```

## 支持的 Markdown 语法

| 语法 | 说明 |
| --- | --- |
| `#` ~ `######` | 六级标题，自动生成锚点 id |
| 段落 | 空行分隔 |
| `**粗体**` / `*斜体*` / `` `行内代码` `` | 行内样式，可嵌套 |
| ` ``` ` 代码块 | 支持语言标注（如 ` ```python `），块内不做行内解析，`< > &` 自动转义 |
| `>` | 引用块，可多行、含行内样式 |
| `-` / `1.` | 无序/有序列表，支持嵌套（对 2/4 空格混用缩进宽容） |
| `[text](url)` / `![alt](src)` | 链接与图片，URL 允许一层嵌套括号 |
| `---` / `***` | 水平线 |
| 表格 | `\|` 分隔、表头下 `---` 分隔行；单元格内的竖线用 `\|` 转义 |
| 行内 / 块级 HTML | 原样透传输出 |

## 站点特性

- **目录结构映射**：`docs/guide/start.md` → `site/guide/start.html`，子目录任意嵌套
- **自动 TOC**：从每页的 h2/h3 提取，渲染在右侧边栏，点击跳转。锚点 id 由标题文本 slug 化（小写、空白转连字符、去标点），中文标题同样生成稳定锚点，重名标题自动加序号去重
- **代码高亮**：自实现的规则着色器（关键词 / 字符串 / 注释 / 数字），内置 Python 规则，其他语言原样转义输出
- **统一模板**：导航栏 + 内容 + 右侧 TOC + 页脚，导航高亮当前页，CSS/链接路径按页面深度自动算相对路径
- **主题**：`default`（浅色）和 `dark`（深色）两套 CSS，构建时拷贝到 `输出目录/assets/style.css`

## 目录结构

```
mdsite/
├── mdsite/
│   ├── markdown.py      # 自实现的 Markdown 解析器（块级 + 行内）
│   ├── highlight.py     # 基于规则的代码着色器
│   ├── template.py      # 自实现的模板引擎
│   ├── builder.py       # 扫描、渲染、套模板、拷资源
│   ├── cli.py           # build / serve 命令
│   ├── templates/page.html  # 页面模板
│   └── themes/          # default.css / dark.css
├── examples/docs/       # 示例文档站点
└── tests/               # pytest 测试
```

## 模板引擎

页面模板在 `mdsite/templates/page.html`，支持三种占位符：

```
{{ title }}                      变量替换（支持 {{ page.title }} 点号取值）
{% if toc %}...{% endif %}       条件块
{% for p in pages %}...{% endfor %}  循环块
```

变量值原样插入（不自动转义），需要转义的内容由构建层先处理好。

## 错误处理

目录不存在、目录里没有 `.md`、文件不可读或不是 UTF-8、主题名写错等情况，
都会输出一行明确报错并以退出码 `2` 结束，不会把 traceback 糊到屏幕上。

## 测试

```bash
python -m pytest
```

覆盖：每种语法元素的解析（标题层级、嵌套列表、表格转义 `\|`、代码块特殊字符转义、
链接/图片边界如空文本与嵌套括号）、TOC 锚点正确性、模板引擎、高亮器，
以及端到端构建（输出结构、TOC 链接可跳转、无占位符残留）和非法输入的报错行为。
