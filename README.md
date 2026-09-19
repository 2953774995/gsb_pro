# minidiff

一个从零实现的迷你 **diff / patch** 工具，仅使用 Python 标准库。

- 差异算法为手写实现：**Myers 贪心差分** + **Hirschberg 线性空间 LCS** 回退
- 不使用 `difflib`，不调用系统 `diff` / `patch`，除 `pytest` 外无任何第三方依赖
- 生成并解析标准 **Unified diff**，支持多 hunk、上下文行数、无末尾换行标记
- 支持补丁的**严格应用、反向应用（reverse）与模糊定位（fuzz）**
- 提供 Python API、`python -m minidiff` 与 `minidiff-cli` 命令行

## 目录结构

```
minidiff/
├── __init__.py      # 公共 API 导出
├── __main__.py      # python -m minidiff 入口
├── cli.py           # 命令行（diff / apply / similarity）
├── exceptions.py    # DiffError
├── _core.py         # Myers 差分 + Hirschberg LCS（核心算法）
├── diff.py          # diff_lines / diff_chars / similarity / Op
├── unified.py       # unified diff 生成、结构化对象与解析
└── patch.py         # apply_patch / reverse_patch
tests/               # pytest 测试套件
minidiff-cli         # 免安装的启动脚本（等价于 python -m minidiff）
pyproject.toml       # 打包与 console_scripts（minidiff / minidiff-cli）
```

## 安装与运行

无需安装，直接在项目根目录运行：

```bash
python3 -m minidiff a.txt b.txt            # 打印 unified diff
python3 -m minidiff diff a.txt b.txt -U 5  # 指定上下文行数
./minidiff-cli a.txt b.txt                 # 等价入口
```

也可以安装为命令行工具：

```bash
pip install .
minidiff a.txt b.txt
minidiff-cli a.txt b.txt
```

### 应用补丁

```bash
# 生成补丁
python3 -m minidiff a.txt b.txt > change.diff

# 应用补丁（标准输出结果，或用 -o 写文件）
python3 -m minidiff apply change.diff a.txt
python3 -m minidiff --apply change.diff a.txt -o result.txt

# 反向应用（b -> a）
python3 -m minidiff apply -R change.diff b.txt

# 模糊匹配：行号发生漂移时，按上下文在附近搜索
python3 -m minidiff apply --fuzz change.diff shifted.txt
python3 -m minidiff apply --fuzz 20 change.diff shifted.txt   # 限定搜索半径
```

相似度统计：

```bash
python3 -m minidiff similarity a.txt b.txt   # 输出 0.0 ~ 1.0
```

CLI 退出码：成功 `0`，补丁无法应用 / 文件不存在等错误 `2`。

## Python API

```python
from minidiff import (
    diff_lines,        # 行级编辑脚本
    diff_chars,        # 字符级编辑脚本（可选功能）
    unified_diff,      # 生成 unified diff 文本
    parse_unified_diff,  # 解析 unified diff 为结构化对象
    apply_patch,       # 应用补丁
    reverse_patch,     # 得到反向补丁文本
    similarity,        # 行相似度（0.0 ~ 1.0）
    DiffError,         # 所有错误统一抛此异常
)

a = "one\ntwo\nthree\n"
b = "one\nTWO\nthree\nfour\n"

# 1) 差异序列
for op in diff_lines(a, b):
    print(op.kind, op.old_no, op.new_no, repr(op.text))
# equal 1 1 'one\n'
# delete 2 None 'two\n'
# insert None 2 'TWO\n'
# equal 3 3 'three\n'
# insert None 4 'four\n'

# 2) unified diff（默认 3 行上下文）
patch = unified_diff(a, b, fromfile="a.txt", tofile="b.txt", context=3)

# 3) 解析回来
structured = parse_unified_diff(patch)
for hunk in structured.hunks:
    print(hunk.old_start, hunk.old_len, hunk.new_start, hunk.new_len)
    for line in hunk.lines:       # line.kind: ' ', '-', '+'
        ...

# 4) 应用 / 反向应用
assert apply_patch(a, patch) == b
assert apply_patch(b, patch, reverse=True) == a
assert reverse_patch(reverse_patch(patch)) == patch

# 5) 模糊匹配（上下文还在，但行号整体偏移）
apply_patch(shifted_text, patch, fuzz=True)     # 全文就近搜索
apply_patch(shifted_text, patch, fuzz=10)       # 仅搜索 ±10 行

# 6) 辅助功能
similarity(a, b)          # 2 * 相同行数 / (len(a) + len(b))
diff_chars("hello", "hallo")
```

`Op` 是一个具名元组：`Op(kind, old_no, new_no, text)`。

- `kind`：`"equal"`（保留）、`"insert"`（新增）、`"delete"`（删除）
- `old_no` / `new_no`：1-based 行号（或字符位置），不属于该侧时为 `None`
- `text`：行文本（保留原始末尾换行符）

输入既可以是字符串（按行切分），也可以是 `list[str]`（列表元素若没有结尾换行
会自动补上）。

## 算法说明

### 最短编辑脚本

两段文本的差异本质上是一个 **最短编辑脚本（SES）** 问题：在“新增一行 / 删除
一行”的代价模型下，把 A 变成 B 的最优脚本长度为 `len(A) + len(B) - 2 * LCS`，
其中 LCS 是最长公共子序列。

`minidiff/minidiff/_core.py` 组合了两种手写的动态规划算法：

1. **Myers 贪心差分（默认路径）**
   论文 *An O(ND) Difference Algorithm and Its Variations*（Eugene W. Myers,
   1986）中的贪心前沿算法。它在编辑图上沿对角线“蛇形”前进，每一轮只维护各条
   对角线上“能到达的最远位置”，并保存每一轮的完整前沿用于回溯。当两段文本只
   有少量改动（最常见的情况）时，复杂度近似 **O((n+m)·d)**，d 是编辑距离，
   因而接近线性；不会出现指数级回溯。

2. **Hirschberg 线性空间 LCS（回退路径）**
   当编辑距离很大（例如两段几乎无关的文本）时，Myers 保存的前沿快照会变多。
   一旦轮数超过预算，自动切换到 Hirschberg 的分治 LCS：每次只保留两行 DP
   （正向一行、反向一行），在中间把问题切两半递归，保证 **O(n·m) 时间、
   O(min(n,m)) 额外空间**，内存绝不随输入平方增长。

此外还有两个 O(n) 快速路径：

- A、B 完全没有公共行时（行集合互不相交），LCS 必为空，直接输出“全删 + 全增”；
- Hirschberg 递归内部先剥离公共前缀和公共后缀，使“大文件、小改动”场景几乎
  线性完成。

测试中通过对数千组随机序列与朴素 O(n·m) DP 的 LCS 长度做比对，证明输出始终
是**最优**（最短）编辑脚本；同时通过源码静态扫描与“屏蔽 `difflib` 导入”的
子进程测试，证明核心算法没有借助 `difflib`。

### Unified diff

`minidiff/minidiff/unified.py` 负责生成与解析，输出格式与标准实现
（`diff -u` / `difflib.unified_diff`）一致：

```
--- a/file
+++ b/file
@@ -2,4 +2,4 @@
 context
-old
+new
 context
```

- hunk 头 `@@ -start,len +start,len @@`：当长度为 1 时省略 `,len`；
  长度为 0（纯插入/纯删除）显示为 `start,0`，起始锚点与 GNU diff 约定相同
  （例如在文件开头插入时为 `@@ -0,0 +1 @@`）。
- 变更间距不超过 `2 × context` 的相邻改动会合并到同一个 hunk；
  `context=0` 时每个改动独立成 hunk。
- 最后一行没有换行符时，生成标准的 `\ No newline at end of file` 标记，
  解析与再次渲染保持往返一致。
- 解析器支持单文件与多文件补丁，会校验 hunk 头声明的旧/新行数，遇到无法识别
  的行或行数不一致时抛出 `DiffError`。

### 补丁应用

`minidiff/minidiff/patch.py` 按顺序处理 hunk：

- 依据每个 hunk 声明的原始行号定位，逐行比对上下文（`' '`）与删除行（`'-'`），
  用上下文 + 新增行（`'+'`）替换；hunk 之间复制未变更的“间隔行”，因此多 hunk
  与行号漂移都能正确处理。
- **严格模式（默认）**：上下文不匹配、行号越界、hunk 相互交叠、空补丁等一律
  抛出 `DiffError`。
- **反向应用**：`reverse=True` 时在内存中交换 `+`/`-` 与新旧行号，无需先把补丁
  文本反转。
- **模糊匹配（fuzz）**：忽略行号偏移，按上下文在目标文本中**由近及远**搜索可以
  匹配的位置。`fuzz=True` 表示全文搜索，`fuzz=N` 表示只在预期位置 ±N 行内搜索；
  完全找不到上下文时仍抛出 `DiffError`。

### 相似度

```
similarity(a, b) = 2 * equal_lines / (len(a) + len(b))
```

取值范围 `0.0`（无公共行）到 `1.0`（完全相同）；两个空输入记为 `1.0`。

## 运行测试

```bash
python3 -m pytest tests/ -v
```

测试覆盖：

- 相同文本空差异、纯新增、纯删除、混合修改、空输入、无末尾换行
- 多 hunk、hunk 合并、上下文行数 `0/1/3/5`
- hunk 头边界（`-0,0`、纯插入/纯删除、长度 1 省略）
- unified diff 生成 → 解析 → 再渲染的往返一致性
- 生成结果与标准库 `difflib.unified_diff` 的逐字符对比（120+ 随机用例）
- apply 后等于目标文本、reverse 还原、空补丁/上下文不匹配/越界/多文件报错
- fuzz 严格失败、fuzz 成功、半径限制、reverse + fuzz
- 字符级 diff 与相似度
- 数千组随机输入下编辑脚本的**最优性**（与朴素 DP 的 LCS 长度对比）
- 2 万行级输入的性能（避免超时）与高 churn 时的 Hirschberg 回退
- CLI（子进程）端到端、退出码
- 源码静态扫描：不导入 `difflib`、不调用 `subprocess`/`popen`/`system`、
  仅使用标准库；以及在子进程中屏蔽 `difflib` 后功能仍正常

## 设计约束

- 仅依赖 Python 标准库（`re`、`collections`、`argparse`、`ast` 等）
- 核心算法（`minidiff/_core.py`、`minidiff/diff.py`）不 import `difflib`
- 不 shell out 到系统 `diff`/`patch`
- 第三方依赖只有测试框架 `pytest`
