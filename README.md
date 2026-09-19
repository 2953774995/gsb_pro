# rex

一个从零实现的迷你正则表达式引擎，仅使用 Python 标准库（匹配逻辑不依赖
`re` 模块，除 pytest 外无任何第三方依赖）。

## 架构设计

```
rex/
├── scanner.py   # 字符扫描器：逐字符读取模式串，解析全部转义序列，产出 Token 流
├── ast.py       # AST 节点定义（Literal/Dot/CharClass/Anchor/Concat/Alternate/Repeat/Group）
├── parser.py    # 递归下降解析器：Token 流 -> AST，负责全部语法错误报告（带列号）
├── matcher.py   # 回溯匹配引擎：基于生成器的深度优先搜索，带步数预算防灾难性回溯
├── pattern.py   # 公共 API：compile() / Pattern / Match，递归深度保护
├── flags.py     # 编译选项：IGNORECASE、MULTILINE
├── errors.py    # RegexError（含原因与列号）与 RegexTimeoutError
├── cli.py       # rex-cli 命令行界面
└── __main__.py  # 支持 python3 -m rex
```

数据流：`pattern 字符串 -> Scanner(转义处理) -> Parser(AST) -> Matcher(回溯搜索) -> Match`

匹配引擎说明：

- 每个 AST 节点对应一个生成器函数，按偏好顺序（贪婪优先 / 非贪婪其次 /
  交替从左到右）产出所有可能的结束位置，天然实现回溯。
- 每次字符比较、锚点判断、重复展开都会消耗共享的"步数预算"
  （默认 1 亿步，可通过 `step_limit` 配置）。预算耗尽即抛
  `RegexTimeoutError`，因此 `(a+)+$` 这类指数级退化模式会安全终止而不是卡死。
- 对能匹配空串的重复（如 `(a?)*`）做了零宽检测，避免无限循环。
- 捕获组通过共享的槽位数组记录，回溯时自动恢复。

## 支持的语法

| 语法 | 说明 |
| --- | --- |
| `abc` | 字面量 |
| `.` | 任意字符（不匹配 `\n`） |
| `^` `$` | 锚点；`MULTILINE` 下匹配行首/行尾（`$` 匹配换行前的位置） |
| `[abc]` `[^abc]` `[a-z0-9]` | 字符类，支持范围、取反、类内转义 |
| `\d \D \w \W \s \S` | 字符类转义（类内外均可） |
| `\n \t \r \\ \. \* \+ \? \( \) \[ \] \|` 等 | 转义字面量 |
| `\xHH` `\uXXXX` | 十六进制转义 |
| `*` `+` `?` `{m}` `{m,}` `{m,n}` | 量词（上限 65535） |
| `*?` `+?` `??` `{m,n}?` | 非贪婪量词 |
| `(...)` | 捕获组（按左括号顺序编号） |
| `(?:...)` | 非捕获组 |
| `(?P<name>...)` | 命名捕获组（不占用数字编号） |
| `a|b` | 交替（从左到右偏好） |

明确不支持的特性：反向引用（`\1`，编译时抛 "not supported" 错误）、
环视（`(?=...)` 等，抛 "unsupported group syntax" 错误）。

## 编译选项

- `rex.IGNORECASE` / `rex.I`：大小写不敏感匹配。
- `rex.MULTILINE` / `rex.M`：`^`/`$` 匹配每行的行首/行尾。

## API 用法

```python
import rex

p = rex.compile(r"(?P<user>\w+)@(?P<host>\w+)", rex.IGNORECASE)
m = p.search("Contact Alice@Example.org")
m.group(0)        # 'Alice@Example'
m.group("user")   # 'Alice'
m.groups()        # ('Alice', 'Example')
m.span()          # (7, 19)

p.findall("a1 b22")                 # 全部命中
for m in p.finditer("a1 b22"):      # 惰性迭代
    print(m.span(), m.groups())
```

`Pattern` 方法：`search` / `match` / `fullmatch` / `findall` / `finditer`。
`Match` 方法：`group()` / `group(n)` / `group(name)` / `groups()` /
`groupdict()` / `span()` / `start()` / `end()`。

## 命令行工具

```bash
# 基本搜索（输出命中位置与捕获组）
./rex-cli '(\w+)@(\w+)' 'contact alice@example.org'

# 大小写不敏感 + 多行 + 列出全部命中
printf 'foo\nbar\nFOO\n' | ./rex-cli -i -m --findall '^foo$'

# 从文件读取文本
./rex-cli --findall '(\d+)' --file data.txt

# 调整单次匹配步数上限
./rex-cli '(a+)+$' 'aaaaaaaaaaaaaaaaaaaaaab' --step-limit 200000
```

也可以用 `python3 -m rex ...` 调用。退出码：`0` 有命中，`1` 无命中，
`2` 非法正则，`3` 匹配超限。

## 错误处理

- 非法正则抛 `rex.RegexError`，消息包含原因与 1 起始的列号，例如
  `unterminated character class (at column 1)`。
- 匹配超过步数上限抛 `rex.RegexTimeoutError`（继承自 `RegexError`）。

## 运行测试

```bash
python3 -m pytest tests/ -v
```
