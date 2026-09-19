# minidiff

一个从零实现的迷你 diff/patch 工具。项目只使用 Python 标准库；运行时不导入 `difflib`，也不调用系统 `diff`、`patch` 或任何外部命令。`pytest` 仅用于开发测试。

## 功能

- 自己实现最短编辑脚本（Shortest Edit Script, SES）：
  - 主算法：Myers O(ND) 差分算法；
  - 大输入/高差异输入的保底算法：Hirschberg 线性空间 LCS 动态规划；
  - 先裁剪公共前缀和公共后缀，常见文件修改接近线性时间。
- 输出逐行操作流：`equal` / `insert` / `delete`，带两侧行号。
- 生成标准 unified diff：
  - `---` / `+++` 文件头；
  - `@@ -start,len +start,len @@` hunk 头；
  - 上下文空格行、`+` 新增行、`-` 删除行；
  - `\ No newline at end of file` 标记；
  - 可配置上下文行数，默认 3。
- 解析 unified diff 为结构化对象，并可再次序列化，支持往返一致。
- 应用补丁：
  - 严格行号匹配或模糊匹配；
  - 反向应用（reverse）；
  - 检测上下文不匹配、行号越界、hunk 计数不一致和空补丁，并抛出 `DiffError`。
- 辅助：
  - 行相似度；
  - 字符级 diff。
- CLI：支持 diff、apply、reverse、输出到文件和上下文参数。

## 目录结构

```text
minidiff/
  __init__.py       # 公共 API
  diff.py           # Myers、Hirschberg/LCS、行/字符 diff、相似度
  unified.py        # unified diff 生成、结构化模型与解析
  patch.py          # apply/reverse、DiffError、模糊定位
  cli.py            # 命令行入口
  __main__.py       # python -m minidiff
minidiff-cli        # 无需安装时的仓库内启动脚本
tests/              # pytest 测试
pyproject.toml      # 打包与 console script 配置
```

## 快速开始

无需安装，直接在仓库根目录运行：

```bash
python3 -m minidiff a.txt b.txt
python3 -m minidiff a.txt b.txt --context 5
python3 -m minidiff --apply change.diff original.txt > result.txt
python3 -m minidiff --apply change.diff new.txt --reverse > original.txt
```

也可以使用仓库内的可执行脚本：

```bash
./minidiff-cli a.txt b.txt
./minidiff-cli --apply change.diff original.txt
```

安装后会得到名为 `minidiff` 的命令：

```bash
python3 -m pip install -e .
minidiff a.txt b.txt
minidiff --apply change.diff original.txt
```

常用 CLI 参数：

| 参数 | 说明 |
| --- | --- |
| `--context, -c N` | diff 上下文字数，默认 3 |
| `--apply PATCH` | 应用补丁而不是生成 diff |
| `--reverse, -R` | 反向应用补丁 |
| `--no-fuzz` | 禁用模糊定位，要求 hunk 出现在声明行号 |
| `--output, -o FILE` | 写入文件；默认写标准输出 |

相同文本生成的 diff 为空字符串。

## Python API

### 行差异：`diff_lines`

```python
from minidiff import diff_lines

ops = diff_lines("a\nb\n", "a\nB\n")
for op in ops:
    print(op.kind, repr(op.value), op.old_start, op.new_start)
```

`DiffOp` 字段：

- `kind`：`equal`、`insert` 或 `delete`；
- `value`：完整行，包含原始换行符；
- `old_start/old_end`、`new_start/new_end`：行号，行 diff 从 1 开始；不适用的一侧为 `None`。

### Unified diff：生成、解析和序列化

```python
from minidiff import unified_diff, parse_unified_diff, render_patch

patch_text = unified_diff(
    "one\ntwo\nthree\n",
    "one\nTWO\nthree\n",
    context=3,
    fromfile="old.txt",
    tofile="new.txt",
)

patch = parse_unified_diff(patch_text)
print(patch.hunks[0].old_start, patch.hunks[0].new_start)
assert render_patch(patch) == patch_text
```

`Patch`、`Hunk`、`HunkLine` 是不可变 dataclass，可用于程序化构造或检查补丁。

### 应用和反向应用补丁

```python
from minidiff import apply_patch, unified_diff

old = "context\nold\ncontext\n"
new = "context\nnew\ncontext\n"
patch = unified_diff(old, new)

assert apply_patch(old, patch) == new
assert apply_patch(new, patch, reverse=True) == old
```

默认 `fuzz=True`：

- 如果 hunk 声明的行号有偏移，会从当前位置之后搜索完全匹配的旧侧上下文/删除块；
- **上下文内容本身必须完全相同**，不会做忽略空白或猜测相似行的匹配；
- 纯插入 hunk 没有旧侧锚点，因此仍然按照声明插入位置应用；
- 设置 `fuzz=False` 后，行号和内容必须同时匹配。

错误统一抛出 `minidiff.DiffError`。空补丁（空字符串或只有文件头）也会在 apply 时报错，因为没有任何可应用的变化。

### 相似度和字符级 diff

```python
from minidiff import similarity, char_diff

print(similarity("a\nb\nc\n", "a\nX\nc\n"))  # 2/3

for op in char_diff("abc", "axc"):
    print(op.kind, op.value, op.old_start, op.new_start)
```

相似度定义为：

```text
LCS 行数 / max(旧行数, 新行数)
```

字符级操作的偏移量从 0 开始。

## 算法说明

### Myers 主算法

Myers 将“删除一行 + 插入一行”看作网格编辑图中的边，沿对角线移动表示保留相同行。算法按编辑距离 `d` 搜索各对角线上能到达的最远位置（snake），保存每个深度的 V 状态用于回溯。第一次到达右下角时，回溯路径就是最短编辑脚本之一。

优点是常见文件（只改少数几行）速度非常快。最坏情况下保存回溯状态约为 O(D²)，所以本项目设置了安全深度上限。

### Hirschberg/LCS 保底算法

当编辑距离非常大时，切换到 Hirschberg 风格的分治 LCS：

- 常规 LCS 表格是 O(nm) 空间；
- 本项目只保存两行 DP，并用分治确定分割点，总体仍是 O(nm) 时间、O(n+m) 额外空间；
- 输出同样补全删除/插入操作，得到完整的最短编辑脚本。

因此算法不会指数级回溯；无论使用 Myers 还是保底路径，结果都满足 SES 最小编辑数。测试通过穷举小规模序列验证了这一点，并用 5000 行近相同文本、900 行几乎完全不同文本检查性能。

### Unified hunk 规则

- 连续变化点按上下文窗口合并；窗口触碰或重叠时合并为一个 hunk。
- 普通一侧长度为 1 时省略 `,1`。
- 纯新增旧侧长度为 0，起始位置采用标准的插入位置（文件顶部为 `0,0`）。
- 纯删除新侧长度为 0。
- 最后一行无换行时输出标准的 no-newline 标记。

## 运行测试

```bash
python3 -m pytest tests/ -v
```

测试覆盖：

- 相同文本、空输入、纯新增、纯删除、混合修改；
- 多 hunk、context=0/2/3/6；
- unified diff 生成、解析、再次渲染的 round-trip；
- apply 到目标文本和 reverse 回原文；
- no-newline、CRLF、行号越界和上下文不匹配；
- 模糊偏移与 `--no-fuzz` 严格模式；
- 字符级 diff 与相似度；
- Myers/Hirschberg 的小规模穷举最优性和大输入性能；
- CLI 和仓库内启动脚本；
- AST 静态检查实现代码未导入 `difflib`、未调用外部 diff/patch，且没有运行时第三方依赖。

## 实现约束

- 运行时代码仅使用 Python 标准库。
- 不使用 `difflib` 做核心算法，也不使用它生成或解析补丁。
- 不调用系统 `diff` / `patch` / `diff3`。
- 不引入运行时第三方包；`pytest` 只存在于测试环境中。
