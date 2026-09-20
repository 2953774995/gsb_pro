# datamask

客服工单敏感信息检测与脱敏工具。核心是一套**自研的模式匹配引擎**（字符扫描 → 递归下降解析 → 显式 AST → 指令编译 → 回溯虚拟机），完全不使用 `re` 模块，仅依赖 Python 标准库，匹配逻辑全程可审计。

## 架构设计

```
datamask/
├── escapes.py    # 字符扫描与转义表（\d \w \s \xHH \uXXXX 等的统一定义）
├── nodes.py      # AST 节点定义（Literal/CharClass/Group/Repeat/Alt/...）
├── parser.py     # 递归下降解析器：模式文本 → 显式 AST，错误带原因与列号
├── compiler.py   # AST → 虚拟机指令序列（量词展开、程序大小保护）
├── vm.py         # 回溯型匹配虚拟机（状态记忆化剪枝 + 步数预算）
├── pattern.py    # 编译选项、compile()、Pattern 与 Match 公开 API
├── rules.py      # 内置敏感信息规则包（手机号/身份证/银行卡/邮箱）与脱敏
├── cli.py        # datamask-cli 命令行入口
└── __main__.py   # python3 -m datamask 入口
```

**数据流**：`模式文本 → Parser → AST → Compiler → 指令序列 → VM 执行 → Match`

### 防灾难性回溯设计

引擎是回溯型匹配器（贪婪优先、非贪婪可用、交替从左到右偏好），但做了两层防护：

1. **状态记忆化剪枝**：本语法不含反向引用，捕获槽的值不影响控制流，因此虚拟机状态完全由 `(指令位置, 文本位置)` 决定。对已探索过的状态做去重剪枝，与纯回溯语义严格等价，但把 `(a+)+$` 这类指数级退化输入降为多项式时间，从根上消除灾难性回溯。
2. **步数预算**：每次指令执行计入预算（默认 1 亿步，可配置），超限抛 `PatternTimeoutError`，双保险保证不卡死进程。

## 模式语法清单

| 语法 | 说明 |
|---|---|
| `abc` | 字面量 |
| `^` `$` | 行首/行尾锚点（Multiline 下匹配每行；`$` 匹配换行前位置） |
| `.` | 任意字符（不匹配换行） |
| `[abc]` `[^abc]` `[a-z0-9]` | 字符类，支持取反、范围、转义；首字符 `]` 与 `-` 为字面量 |
| `\d \D \w \W \s \S` | 字符类缩写（分组外与字符类内均可） |
| `\n \t \r \\` 等 | 控制字符与标点转义（任意非字母数字字符转义后为字面量） |
| `\xHH` `\uXXXX` | 十六进制转义 |
| `*` `+` `?` `{m}` `{m,}` `{m,n}` | 量词（`n` 上限 65535）；后缀 `?` 为非贪婪 |
| `( )` `(?: )` `(?P<name> )` | 捕获、非捕获、命名捕获；编号按左括号出现顺序 |
| `a|b` | 交替，从左到右偏好 |

**明确不支持的特性**：反向引用 `\1`（抛"不支持"错误）、环视 `(?=...)` 等（抛"未知分组扩展"错误）、未知字母转义（抛"未知转义"错误）。所有非法模式抛 `PatternError`，错误信息带原因描述与出错列号（0 起始）。

## API 用法

```python
import datamask

p = datamask.compile(r'(?P<area>\d{3,4})-(\d{7,8})', flags=datamask.MULTILINE)
m = p.search('热线 010-12345678')
m.group('area')        # '010'
m.groups()             # ('010', '12345678')
m.span()               # (3, 14)

p.findall(text)        # 无组→命中串列表；一组→该组列表；多组→元组列表
for m in p.finditer(text):   # 惰性迭代器
    ...

# 编译选项：datamask.IGNORECASE / datamask.MULTILINE
# 步数预算：datamask.compile(pat, max_steps=10**6) 或每次调用时传 max_steps=
```

## 规则包与脱敏

内置四类规则（用 datamask 自身语法书写，见 `datamask/rules.py`）：

| 规则名 | 模式 | 脱敏效果 |
|---|---|---|
| `mobile` | `(1[3-9]\d)(\d{4})(\d{4})` | `13812345678` → `138****5678` |
| `idcard` | `(\d{6})(\d{8})(\d{3}[\dXx])` | `11010119900307123X` → `110101********123X` |
| `bankcard` | `(\d{4})(\d{8,11})(\d{4})` | `6222021234567890123` → `6222***********0123` |
| `email` | 本地部分+域名分组 | `alice.w@gmail.com` → `a***@gmail.com` |

```python
from datamask import detect, mask

detect('打 13812345678 联系我')        # [{'rule': 'mobile', 'span': (2, 13), ...}]
mask('打 13812345678 联系我', 'mobile')  # '打 138****5678 联系我'
mask(text, 'all')                       # 应用全部规则（同起点取最长命中）
```

## 命令行工具

```bash
# 直接使用仓库根目录的启动脚本（或 pip install . 后用 datamask-cli）
./datamask-cli '(?P<area>\d{3,4})-(\d{7,8})' '热线 010-12345678'
# match 1: span=(3, 14) text='010-12345678'
#   groups: ('010', '12345678')
#   group 'area': '010'
# count: 1

echo 'AbC dEf' | ./datamask-cli --ignore-case --findall '[a-z]+'
./datamask-cli --multiline '^ERROR' --file server.log
./datamask-cli --mask mobile '联系电话 13812345678'     # 输出: 联系电话 138****5678
./datamask-cli --mask all --file ticket.txt             # 全部规则脱敏
```

选项：`--ignore-case`、`--multiline`、`--findall`、`--file <path>`、`--mask <规则名|all>`、`--max-steps <N>`。文本来源优先级：`--file` > 位置参数 > 标准输入。退出码：命中/成功为 0，未命中为 1，错误为 2。

## 运行测试

```bash
python3 -m pytest tests/ -v
```

测试覆盖：字面量与转义边界、字符类（取反/范围/空类）、量词边界（零次/一次/上限/非贪婪）、分组与嵌套捕获（含命名捕获）、锚点与 Multiline 语义、交替优先级、非法模式错误（含列号断言）、灾难性回溯超时防护（确认快速失败）、findall/finditer 迭代语义、空模式与空输入边界、四类敏感信息的命中与脱敏结果、CLI 全选项。

## 约束

- 仅使用 Python 标准库（`argparse`、`sys`），被测代码零第三方依赖（测试框架 pytest 除外）
- 不使用 `re` 模块实现任何匹配逻辑
- 兼容 Python 3.8+
