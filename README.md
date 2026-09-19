# minigit

`minigit` 是一个用 **Python 标准库从零实现** 的迷你 Git 核心。它实现了内容寻址对象库、二进制索引、分支引用、工作区还原、状态检查、简化差异比较与重置操作。

运行和测试均不需要第三方运行时依赖；测试仅使用 `pytest`。代码不会调用 `git`，也不会通过 `subprocess`、Shell 或其他外部进程来实现版本控制功能。

## 环境与启动

要求 Python 3.9+。

在项目根目录中可以直接以模块方式运行：

```bash
python3 -m minigit init
python3 -m minigit add .
python3 -m minigit commit -m "initial commit"
python3 -m minigit log
```

也可以把项目根目录加入 `PYTHONPATH` 后，在其他目录中运行：

```bash
PYTHONPATH=/path/to/task-07-minigit-a python3 -m minigit init /path/to/repo
```

所有命令在当前目录或父目录中查找 `.minigit/`。未找到仓库时会输出明确错误并返回退出码 `1`。

## 支持命令

| 命令 | 说明 |
| --- | --- |
| `init [path]` | 创建 `.minigit/` 仓库结构；省略 `path` 时使用当前目录 |
| `add <path>...` | 添加文件或目录；给已删除的已跟踪路径执行 add 会暂存删除 |
| `commit -m <msg>` | 从索引递归构建 tree 和 commit，并推进当前分支 |
| `commit -m <msg> --allow-empty` | 即使索引与 HEAD 相同也创建空提交 |
| `log [--oneline] [<commit>]` | 沿第一父链查看提交历史 |
| `branch` | 列出本地分支，当前分支前显示 `*` |
| `branch <name>` | 基于当前 HEAD 创建分支 |
| `checkout <branch>` | 切换 HEAD、还原索引与工作区，保留未跟踪文件 |
| `status` | 显示 staged、modified、deleted、untracked 状态 |
| `status --short` / `-s` | 紧凑两列状态输出 |
| `diff` | 默认比较工作区与索引 |
| `diff --cached` / `--staged` | 比较索引与 HEAD |
| `diff --stat` | 输出每个文件的增删行统计 |
| `reset --soft <commit>` | 只移动当前分支指针，工作区和索引不变 |
| `reset --mixed <commit>` | 移动分支指针并把索引重置到目标提交，工作区不变 |

缺少参数、未知子命令、未初始化、引用不存在、checkout 不存在的分支等情况都会打印 `minigit: error: ...` 并返回非零退出码。

## 提交与空提交约定

- 第一次提交没有 `parent`。
- 后续提交的 `parent` 指向当前分支 HEAD。
- 索引内容与 HEAD 完全相同时，普通 `commit` 不会创建提交，输出 `nothing to commit...` 并返回 `1`。
- 需要显式创建空提交时使用 `--allow-empty`。

作者信息可通过环境变量覆盖：

- `MINIGIT_AUTHOR_NAME` 或 `GIT_AUTHOR_NAME`
- `MINIGIT_AUTHOR_EMAIL` 或 `GIT_AUTHOR_EMAIL`

## 对象库格式

对象目录为：

```text
.minigit/objects/xx/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

其中 `xx` 是 SHA-1 前两位，其余 38 个十六进制字符作为文件名。

对象文件是 zlib 压缩后的 Git 风格对象：

```text
<type> <size>\0<content>
```

对象 ID 为上述完整字节流的 SHA-1：

```python
sha1(b"blob 13\0" + b"hello object\n")
```

支持三类对象：

### blob

blob 内容就是文件字节。相同内容即使来自不同文件名也会得到相同 SHA-1，因此自动去重。大文件通过 1 MiB 分块流式读取、哈希与压缩，避免一次性读入内存。

### tree

tree 保存目录项列表。每个目录项记录：

```text
<mode> <name>\0<20-byte raw sha-1>
```

常见模式：

- `100644`：普通文件
- `100755`：可执行文件
- `40000`：子目录

写入时从索引的扁平路径递归构建子 tree。同一层按名称的 UTF-8 字节稳定排序，因此相同输入总能得到相同 tree hash。

### commit

commit 为文本格式：

```text
tree <tree-sha1>
parent <parent-sha1>      # 首提交无此行
author <Name> <email> <unix-time> <timezone>
committer <Name> <email> <unix-time> <timezone>

提交消息
```

当前历史沿第一个 parent 向前遍历。

## 引用格式

```text
.minigit/
  HEAD
  refs/
    heads/
      main
      feature
```

`HEAD` 是符号引用，例如：

```text
ref: refs/heads/main
```

分支文件直接保存 40 位 commit hash。`commit` 成功后会覆盖当前分支文件，从而自动推进分支。

## 索引格式

索引文件路径为 `.minigit/index`，采用稳定、紧凑、可复现的二进制格式。

### 头部

大端编码：

| 字段 | 类型 | 内容 |
| --- | --- | --- |
| magic | 7 bytes | 固定为 `MNGIDX\x01` |
| entry count | uint16 | 索引项数量 |

### 索引项

每个条目依次为：

| 字段 | 类型 | 内容 |
| --- | --- | --- |
| mode | uint16 | 八进制 Unix 模式，如 `100644` |
| hash | 20 bytes | 原始 SHA-1 blob hash |
| path length | uint16 | UTF-8 路径字节长度 |
| path | bytes | 规范化后的相对路径，使用 `/` 分隔 |

条目始终按路径的 UTF-8 字节排序。写入使用临时文件原子替换，避免得到半截索引。

## 状态语义

`status` 比较三棵“树”：

1. HEAD 指向的 tree
2. `.minigit/index`
3. 当前工作区

紧凑格式的两列含义与 Git 类似：

- 第一列：索引相对 HEAD 的状态
- 第二列：工作区相对索引的状态

常见输出：

| 输出 | 含义 |
| --- | --- |
| `A  path` | 新文件已暂存 |
| `M  path` | 修改已暂存 |
| `D  path` | 删除已暂存 |
| ` M path` | 工作区已修改但未暂存 |
| ` D path` | 工作区中文件已删除但未暂存 |
| `?? path` | 未跟踪文件或目录 |

## diff

默认 `diff` 比较工作区与索引；`diff --cached` 比较索引与 HEAD。输出基于 Python `difflib` 的简化 unified diff，包含：

- `--- a/path`、`+++ b/path`
- `@@ -old-start,old-count +new-start,new-count @@`
- 行级 `-` / `+` / 上下文
- 最多 3 行上下文

`--stat` 汇总每个文件的插入和删除行数。二进制文件会给出简化的二进制差异提示。

## .minigitignore

忽略规则文件位于仓库根目录 `.minigitignore`。空行和以 `#` 开头的行被忽略。

支持的基础规则：

- `*`：匹配除 `/` 外的任意数量字符，例如 `*.log`
- `?`：匹配除 `/` 外的一个字符
- 不含 `/` 的模式可匹配任意层级的同名文件或目录，例如 `build/`
- 以 `/` 开头表示从仓库根目录锚定，例如 `/config-root.txt`
- 中间包含 `/` 的模式相对根目录匹配，例如 `docs/*.md`
- 以 `/` 结尾表示只匹配目录，例如 `dist/`
- 前后缀形式可直接使用，例如 `prefix*`、`*suffix.tmp`

`.minigit/` 内部目录永远不会被添加或显示为未跟踪文件。

## checkout 工作区规则

切换分支时：

- 目标提交存在、当前跟踪集合中不存在的文件会被删除。
- 目标提交中的文件会被覆盖成目标 blob 内容。
- 不属于当前索引/HEAD 跟踪集合的未跟踪文件会保留。
- 如果切换会覆盖本地修改或未跟踪文件，会中止切换并报错，避免丢数据。
- 切换后索引重置为目标 tree，`HEAD` 指向目标分支。

## 代码组织

```text
minigit/
  __main__.py      # python -m minigit 入口
  cli.py           # 参数解析、命令分发、统一错误处理
  commands.py      # 高层子命令逻辑
  repository.py    # .minigit 路径结构与仓库发现
  objects.py       # blob/tree/commit 内容寻址对象库
  index.py         # 稳定二进制索引读写
  refs.py          # HEAD 与 refs/heads 分支管理
  commits.py       # commit 序列化、解析与历史遍历
  workspace.py     # add 遍历、文件哈希、checkout 工作区还原
  status.py        # 三态状态计算与格式化
  diff.py          # unified diff 与 --stat
  ignore.py        # .minigitignore glob 规则
  errors.py        # 用户可见异常类型
```

## 运行测试

```bash
python3 -m pytest tests/ -v
```

测试全部在 pytest 的临时目录中创建仓库，不会污染当前工作区。测试覆盖对象哈希与去重、tree 顺序、提交父子关系、分支和 checkout、status、删除、diff、忽略规则、reset、未初始化错误、空提交约定和数 MB 大文件添加。
