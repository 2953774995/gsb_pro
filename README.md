# rex — 迷你正则表达式引擎

`rex` 是一个从零实现的纯 Python 正则表达式引擎，支持模式匹配、查找与捕获。
**零第三方依赖**（仅测试使用 pytest），匹配逻辑完全自研，**不使用 `re` 模块**。

## 架构设计

```
rex/
├── errors.py     # RegexError（带列号）/ RegexTimeoutError（继承 RegexError）
├── scanner.py    # 字符扫描与转义表：\d \w \s \n \xHH \uXXXX 等转义解码
├── ast_nodes.py  # 显式 AST 节点定义（dataclass）
├── parser.py     # 递归下降解析器：pattern 文本 -> AST
├── matcher.py    # 回溯匹配引擎（生成器 + 显式栈，带步数预算）
├── pattern.py    # 编译选项、Pattern / Match API、compile()
├── cli.py        # rex-cli 命令行工具
└── __main__.py   # python -m rex 入口
```

**工作流程**：`compile()` 用 `Parser` 把模式文本解析为显式 AST；`Pattern`
的每个匹配操作创建一个带步数预算的 `Context`，由 `matcher` 中的生成器
按回溯偏好顺序（贪婪优先、交替从左到右）惰性地产出 `(end, captures)`。

**防栈溢出**：`*`/`+`/`{m,n}` 重复与序列连接都用**显式栈**而非 Python 递归
实现，长输入（如 `.*` 匹配 20 万字符）不会触发 `RecursionError`。

**防灾难性回溯**：每次匹配操作有步数上限（默认 1 亿，可用
`compile(..., max_steps=N)` 配置），超限抛 `RegexTimeoutError`。
`(a+)+$` 等经典退化模式会在预算内安全终止。

## 支持的语法

| 类别 | 语法 |
|---|---|
| 字面量 | 普通字符；`\.` `\*` `\+` `\?` `\(` `\)` `\[` `\]` `\|` `\\` 等转义 |
| 锚点 | `^` `$`（Multiline 下匹配行首/行尾，`$` 匹配换行前位置） |
| 通配 | `.`（不匹配换行） |
| 字符类 | `[abc]` `[^abc]` `[a-z0-9]`、类内转义、`[\d]`、`[]]` 等 |
| 转义序列 | `\d \D \w \W \s \S` `\n \t \r \f \v \a` `\xHH` `\uXXXX` |
| 量词 | `*` `+` `?` `{m}` `{m,}` `{m,n}`（n ≤ 65535），非贪婪后缀 `*?` `+?` `??` `{m,n}?` |
| 分组 | `(...)` 捕获、`(?:...)` 非捕获、`(?P<name>...)` 命名捕获 |
| 交替 | `a|b|c`（从左到右偏好） |

**语义细节**：

- 捕获组按左括号出现顺序编号；**命名组不占用编号**，仅按名字访问
  （`m.group("name")` / `m.groupdict()`）。
- 反向引用 `\1` 未实现：编译时抛出带"not supported"说明的 `RegexError`。
- 非 Multiline 时 `$` 只匹配文本末尾（不像 Python `re` 那样容忍末尾换行）。
- 空匹配允许；`finditer` 在空匹配后前进一个字符继续扫描。

## API 速览

```python
import rex

p = rex.compile(r"(?P<year>\d{4})-(\d{2})", flags=rex.IGNORECASE | rex.MULTILINE)
m = p.search("date: 2024-01")
m.group()          # '2024-01'   （group(0) 为整体命中）
m.group(1)         # '01'        （编号组）
m.group("year")    # '2024'      （命名组）
m.groups()         # ('01',)     （编号组元组）
m.span()           # (6, 13)；start()/end()/span(n)/span(name) 同理

p.findall(text)    # 无编号组 -> 命中串列表；1 个编号组 -> 该组列表；否则元组列表
for m in p.finditer(text):   # 惰性迭代全部命中
    ...
```

编译选项：`rex.IGNORECASE`（别名 `rex.I`）、`rex.MULTILINE`（别名 `rex.M`）。

## 命令行工具 rex-cli

```bash
# 安装后获得 rex-cli 命令（也可以直接用 python -m rex）
pip install .

# 基本搜索：输出命中位置、捕获组与命中次数
rex-cli '(\w+)@(\w+)' 'contact alice@example.com'
# match 1: span=(8, 21) text='alice@example'
#   group 1: 'alice' span=(8, 13)
#   group 2: 'example' span=(14, 21)
# 1 match(es) found

# 从标准输入读文本
echo 'a1 b22 c333' | rex-cli '\d+'

# 从文件读文本，多行模式
rex-cli --file log.txt -m '^\w+'

# findall 模式 / 忽略大小写 / 调整步数上限
rex-cli --findall '(\d)(\d)' '12 34'
rex-cli -i 'hello' 'say HELLO'
rex-cli '(a+)+$' 'aaaaaaaaaaaaaaaaaaaaaab' --max-steps 100000   # 退出码 3
```

退出码：`0` 正常；`2` 非法正则或文件错误；`3` 匹配超步（`RegexTimeoutError`）。

## 错误处理

非法正则在编译期抛出 `rex.RegexError`，消息包含原因与 1 起始列号：

```python
>>> rex.compile("(abc")
rex.errors.RegexError: unclosed group at column 1
>>> rex.compile("a{3,2}")
rex.errors.RegexError: min repeat greater than max repeat at column 2
>>> rex.compile(r"(a)\1")
rex.errors.RegexError: backreferences (\1..\9) are not supported at column 4
```

覆盖：未闭合括号/字符类、量词位置非法（`a**`、`^*`）、未知转义、
`{m,n}` 中 `m>n` 或超过 65535、命名捕获重名、非法字符范围等。

## 运行测试

```bash
python3 -m pytest tests/ -v
```

测试覆盖：字面量与转义边界、字符类（取反/范围/空类）、量词边界
（零次/一次/上限/非贪婪）、分组与嵌套捕获（含命名捕获）、锚点与
Multiline 语义、交替优先级、非法正则错误（含列号断言）、灾难性回溯
超时防护（快速失败）、findall/finditer 迭代语义、空模式与空输入边界、
CLI 端到端。
