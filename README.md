# datamask

客服工单敏感信息检测与脱敏工具。安全合规要求工单文本导出给外包团队前，
先对**手机号、身份证号、银行卡号、邮箱**等敏感信息做检测与脱敏。

核心特征：**模式匹配引擎完全自研、可审计**——不使用 `re` 模块，不依赖任何
第三方包（仅测试使用 pytest），纯 Python 标准库实现。

## 架构设计

```
模式字符串
   │
   ▼
scanner.py   字符扫描器 + 转义表（SIMPLE_ESCAPES / CLASS_SHORTHANDS）
   │
   ▼
parser.py    递归下降解析器 ──► nodes.py 显式 AST
   │                            （Literal/AnyChar/CharClass/Anchor/
   │                             Concat/Alternate/Group/Repeat）
   ▼
compiler.py  AST ──► 线性指令序列（char/any/class/split/jmp/save/
   │                  mark/check/bol/eol/match）
   ▼
engine.py    回溯 VM：显式回退栈（无递归深度风险）+ 步数预算计数器
   │
   ▼
pattern.py   Pattern / Match 公共 API（compile/search/match/...）
```

- **rules.py**：用本工具自己的模式语法编写的四类敏感信息规则 + mask 能力
- **cli.py** / **datamask-cli**：命令行入口
- **errors.py**：`PatternError`（带原因与列号）、`PatternTimeoutError`

### 防灾难性回溯

每条 VM 指令执行都计入共享步数计数器，单次匹配操作超过预算
（默认 **1 亿步**，`compile(..., max_steps=N)` 可配）即抛
`PatternTimeoutError`。`(a+)+$`、`(a|a)*$` 等经典退化模式配合超长输入
会在预算内快速失败，不会卡死进程。空循环（如 `(a*)*`）通过编译期注入的
`mark/check` 指令检测零宽迭代并退出循环，不会死循环。

## 模式语法清单

| 类别 | 语法 |
|---|---|
| 字面量 | 普通字符；`{` 在不构成合法量词时按字面量处理 |
| 锚点 | `^` `$`（Multiline 下匹配行首/行尾，`$` 匹配换行前位置） |
| 通配 | `.` 匹配除换行外的任意字符，`.*` 不跨行 |
| 字符类 | `[abc]` `[^abc]` `[a-z0-9]`；`]` 在首位为字面量；`-` 在首尾为字面量 |
| 转义 | `\d \D \w \W \s \S \n \t \r \\ \. \* \+ \? \( \) \[ \] \|` 及 `\{ \} \^ \$ \-`；`\xHH`、`\uXXXX` 十六进制转义 |
| 量词 | `*` `+` `?` `{m}` `{m,}` `{m,n}`（n ≤ 65535）；非贪婪后缀 `*?` `+?` `??` `{m,n}?` |
| 分组 | 捕获 `( )`、非捕获 `(?: )`、命名捕获 `(?P<name>...)` |
| 交替 | `a|b|c`，按从左到右偏好 |

语义约定：

- 捕获组按左括号出现顺序编号（从 1 开始），命名组同样占用编号
- 贪婪优先、非贪婪可用；`*` 允许零次；空匹配允许
- 重复中的捕获组保留**最后一次迭代**的值
- 非 Multiline 下 `$` 只匹配字符串末尾（严格语义）
- `\d`=`str.isdecimal()`，`\w`=字母数字加下划线，`\s`=`str.isspace()`（Unicode 感知）
- 反向引用 `\1`、`(?P=name)`、断言 `(?=...)` 为**非目标特性**，遇到抛
  `PatternError`（明确报"不支持"）

## Python API

```python
import datamask as dm

p = dm.compile(r'(?P<area>\d{3,4})-(?P<num>\d{7,8})')
m = p.search('总机 010-12345678 转人工')
m.group()        # '010-12345678'
m.group('num')   # '12345678'
m.groups()       # ('010', '12345678')
m.span()         # (3, 14)

p.findall(text)      # 无分组→命中串列表；1 个分组→该组列表；多分组→元组列表
for m in p.finditer(text):   # 惰性迭代
    ...

p = dm.compile(r'^error', dm.IGNORECASE | dm.MULTILINE)
p = dm.compile(r'(a+)+$', max_steps=1_000_000)   # 自定义步数上限
```

异常：`PatternError(message, column)`（`str()` 含列号）；
`PatternTimeoutError` 继承自 `PatternError`。

## 内置规则包

| 规则名 | 模式 | 脱敏效果 |
|---|---|---|
| `phone` | `(1[3-9]\d)(\d{4})(\d{4})` | `13812345678` → `138****5678` |
| `idcard` | `(\d{6})(\d{8})(\d{3}[0-9Xx])` | `11010119900307777X` → `110101********777X` |
| `bankcard` | `(\d{4})(\d{8,11})(\d{4})` | `6222020200112233445` → `6222***********3445` |
| `email` | 见 `rules.py` | `zhangsan@example.com` → `z***@example.com` |

```python
import datamask as dm
dm.list_rules()                          # ['bankcard', 'email', 'idcard', 'phone']
dm.mask_text('手机13812345678', 'phone')  # '手机138****5678'
rule = dm.get_rule('phone')
rule.mask_text(text)                     # 脱敏
list(rule.finditer(text))                # 仅检测
```

脱敏规则按规则名配置：每条规则的 `mask_spec` 是 `[(捕获组号, 替换内容), ...]`，
替换内容可以是固定字符串，也可以是接收该组文本、返回脱敏串的函数
（如银行卡按原长度生成 `*`）。

> 注意：手机号规则会命中身份证号/银行卡号中形如 `1xxxxxxxxxx` 的 11 位片段。
> 多规则联合脱敏时建议先脱敏长号码（idcard/bankcard），再脱敏 phone。

## 命令行工具

```bash
# 搜索：输出命中位置、命中次数与捕获组
./datamask-cli '(\d{4})-(\d{2})-(\d{2})' '工单日期 2026-09-20'
# match 1: span=(5, 15) text='2026-09-20' groups=('2026', '09', '20')
# total: 1 match(es)

# 从标准输入读文本 + findall
echo 'a1b22' | ./datamask-cli '\d+' --findall

# 忽略大小写 / 多行 / 从文件读取
./datamask-cli -i -m '^error' --file ticket.log

# 内置规则脱敏，直接输出脱敏后文本
./datamask-cli --mask phone '联系我 13812345678'     # 联系我 138****5678
echo '邮箱 zhangsan@example.com' | ./datamask-cli --mask email

# 其它
./datamask-cli --list-rules            # 列出全部内置规则
./datamask-cli --max-steps 1000000 '(a+)+$' "$(python3 -c 'print("a"*30+"b")')"
# -> PatternTimeoutError，退出码 2
```

选项：`-i/--ignore-case`、`-m/--multiline`、`--findall`、`--file PATH`、
`--mask RULE`、`--max-steps N`、`--list-rules`。
非法模式/未知规则退出码为 2，错误信息带原因与列号。
也可以 `python3 -m datamask ...` 等价调用。

## 测试

```bash
python3 -m pytest tests/ -v
```

覆盖：字面量与转义边界、字符类（取反/范围/空类）、量词边界（零次/一次/
上限/非贪婪）、分组与嵌套捕获（含命名捕获）、锚点与 Multiline 语义、
交替优先级、非法模式错误（含列号断言）、灾难性回溯超时防护（快速失败）、
findall/finditer 迭代语义、空模式与空输入边界、四类敏感信息命中与脱敏、
CLI 全选项。

## 目录结构

```
datamask/
  __init__.py    公共 API 导出
  options.py     编译选项（IGNORECASE/MULTILINE）与常量
  errors.py      PatternError / PatternTimeoutError
  scanner.py     字符扫描器 + 转义表
  nodes.py       AST 节点定义
  parser.py      递归下降解析器
  compiler.py    AST -> VM 指令序列
  engine.py      回溯 VM（步数预算、空循环保护）
  pattern.py     Pattern / Match / compile()
  rules.py       敏感信息规则包 + mask
  cli.py         命令行入口
  __main__.py    python -m datamask
datamask-cli     可执行启动脚本
tests/           pytest 测试套件
```
