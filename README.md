# minigit

一个**从零实现**的迷你 Git 版本控制核心，使用 **Python 3 标准库**构建（测试用 pytest）。
**不依赖任何第三方运行时包，也不通过 subprocess 调用 git 或其他外部命令。**

## 功能总览

| 能力 | 说明 |
| --- | --- |
| 对象库 | `blob` / `tree` / `commit` 三类对象，SHA-1 内容寻址，zlib 压缩存储 |
| 从当前目录向上查找 `.minigit` | 未初始化时报明确错误并返回非零 |
| `init` | 创建 `.minigit` 幂等目录结构 |
| `add` | 写 blob、更新索引；支持多文件、目录、`.`、可执行位、暂存删除 |
| `commit -m` | 从索引递归构建 tree 与 commit，parent 指向当前 HEAD；首提交无 parent |
| `log` / `log --oneline` | 沿 parent 链打印完整日志或紧凑版（短 hash + 首行消息） |
| `branch` / `branch <name>` | 列出分支（当前分支前缀 `*`）/ 在当前 HEAD 建分支 |
| `checkout <branch>` | 切换 HEAD、按目标树还原工作区与索引；保留未跟踪文件 |
| `status` / `status --short` | 三态（staged / modified / untracked）+ deleted 区分 |
| `diff` | 默认“工作区 vs 索引”；`--cached` 为“HEAD vs 索引”；`--stat` 统计增删行 |
| `.minigitignore` | 基础 glob：`*`、`?`、目录 `/`、前导 `/` 根锚定、含斜杠锚定 |
| `reset --soft` | 仅移动当前分支指针，工作区与索引不动 |
| `reset --mixed`（默认） | 移动分支指针并把索引重置为目标提交的树（工作区不动） |
| 空提交约定 | 无改动时 `commit` 报错退出码 1；首提交空索引允许 `--allow-empty` |
| 大文件 | 文件以 1 MiB 流式分块哈希与压缩，不整文件读入内存，不会卡死 |

## 目录结构

仓库元数据全部放在工作区根目录的 `.minigit/` 下：

```text
.minigit/
├── HEAD                  # 符号引用文本：ref: refs/heads/main
├── index                 # 二进制索引（见下）
├── objects/
│   ├── ab/
│   │   └── cdef0123...   # 2 字符目录 + 38 位文件名（恰好是对象 SHA-1）
│   └── ...
│   └── tmp/              # 写入中间态（原子 rename 前）
└── refs/
    └── heads/
        ├── main          # 每个分支一个文件，内容为指向的 commit SHA-1
        └── dev
```

## 对象格式（松散对象）

与 git 松散对象的精神一致。一个对象的**帧（frame）**为：

```text
<type> SP <body 字节数十进制> NUL <body>
```

- 对整帧计算 SHA-1，得到 40 位十六进制对象 id；
- 帧经 `zlib`（level 6）压缩后写入 `objects/<前2位>/<后38位>`；
- 写盘采用「临时文件 + 原子 `os.replace`」；同内容对象只存一份（blob 天然去重，
  同一文件多次 `add` 不产生新对象）。

**blob**：body 就是文件的原始字节。

**tree**：body 为若干条记录的拼接，递归表达目录层级：

```text
<mode> SP <name> NUL <20 字节原始 SHA-1 摘要><mode> SP <name> NUL <...> ...
```

- 普通文件 `100644`、可执行文件 `100755`、目录 `40000`（均为八进制字符串）；
- 目录按 git 兼容的方式排序——排序键里目录名视为末尾追加 `/`，保证
  构建顺序确定、与插入顺序无关；
- `build_tree(entries)` 接收扁平映射 `{"dir/file": (mode, blob_sha)}`，
  内部递归建子树并返回根 tree 的 SHA-1。

**commit**：文本格式：

```text
tree <root-tree-sha>
parent <parent-sha>          # 每个父提交一行；首个提交没有此行
author <Name> <<email>> <unix 秒> <+/-HHMM>
committer <Name> <<email>> <unix 秒> <+/-HHMM>

<提交消息（可多行，以一个换行结尾）>
```

内部 API 位于 `minigit/objects.py`：

- `hash_object(type, data) -> sha`
- `write_object(repo, type, data) -> sha`（幂等、去重）
- `read_object(repo, sha) -> (type, body_bytes)`
- `write_blob / read_blob`、`build_tree / read_tree / flatten_tree`、
  `write_commit / read_commit`

## 索引格式 `.minigit/index`

自定义的紧凑二进制格式，**稳定可复现**（条目按路径排序；不记录时间戳/inode
等宿主相关数据），相同暂存内容总是序列化出相同字节：

```text
偏移   大小    字段
0      4      魔数 "MIDX"
4      2      版本号 uint16 大端（当前为 1）
6      4      条目数 uint32 大端
10     ...    条目（按 path 字典序），每条：
              mode     uint32 大端（如 100644）
              sha      20 字节原始 SHA-1
              path_len uint16 大端
              path     path_len 字节的 UTF-8 路径
```

## 引用与 HEAD

- `.minigit/HEAD` 保存符号引用：`ref: refs/heads/main`；
- `refs/heads/<branch>` 每个分支一个文本文件，内容是 commit 的 40 位 SHA-1；
- `commit` 成功后自动推进当前分支；
- 引用可按「分支名 / 40 位完整 hash / 唯一的短 hash 前缀」解析，
  无法解析时报 `unknown revision` 错误并以非零退出。

## 命令清单

```text
minigit init
minigit add <path>...                  # 也可用 "."；删除已跟踪文件后 add 该路径即暂存删除
minigit commit -m <msg> [--allow-empty]
minigit log [--oneline] [<ref>]
minigit branch                         # 列出分支，当前分支前有 *
minigit branch <name>                  # 在当前 HEAD 创建分支
minigit checkout <branch>              # 切换分支并还原工作区/索引
minigit status [--short|-s]
minigit diff [--cached|--staged] [--stat] [<commit>]
minigit reset [--soft|--mixed] <commit>   # 默认 --mixed
```

### checkout 的工作区三情形

切到目标提交时：

1. **新增**：目标树中存在、当前索引中不存在的文件写入工作区；
2. **覆盖**：已跟踪文件内容用目标 blob 覆盖（含可执行位）；
3. **删除**：当前索引中跟踪、目标树中不存在的文件被删除，并向上清理空目录。

未跟踪文件一律保留；但若某个未跟踪文件恰好会被目标版本覆盖，
为避免数据丢失，会报错 `untracked working tree file ... would be overwritten`
并以非零退出。

### status 三态与 deleted

- staged：索引与 HEAD 树不同（`A` 新增 / `M` 修改 / `D` 删除）；
- modified：工作区文件与索引条目（内容或可执行位）不同；
- deleted：工作区中已跟踪文件不存在，明确区分为 `D`；
- untracked：磁盘有、索引与 HEAD 都没有（`.minigitignore` 命中的不显示）。

`--short` 使用 git 风格两位状态码，如 `M  file`、` M file`、` D file`、`?? new`。

### diff

- 默认比较**工作区 vs 索引**（`git diff` 语义）；
- `--cached` / `--staged` 比较**HEAD vs 索引**；
- 给提交参数时比较**该提交 vs 工作区**；
- 输出简化 unified diff：`---/+++` 头、`@@ -a,c +b,c @@` 定位、行级 `+/-`、
  默认 3 行上下文，末尾无换行会打印 `\ No newline at end of file`；
- 行级算法为 LCS（O(n·m) 动态规划），对调换两行等情况给出正确结果；
- `--stat` 逐文件统计新增/删除行数并输出汇总。

### .minigitignore

在仓库根目录放 `.minigitignore`，每行一条；空行与 `#` 注释忽略；
`!` 取反不支持（按注释处理）。`.minigit/` 元数据目录**永远**被忽略与剪枝。

| 写法 | 含义 |
| --- | --- |
| `foo.txt` | 任意深度下名为 `foo.txt` 的文件/目录 |
| `*.log` | `*` 匹配任意数量的非 `/` 字符，任意深度 |
| `file?.txt` | `?` 匹配恰好一个非 `/` 字符 |
| `build/` | 仅匹配任意深度名为 `build` 的**目录**（遍历时剪枝） |
| `/main.log` | 只匹配仓库根目录下的 `main.log` |
| `docs/note.md` | 含斜杠，锚定整路径，只匹配根下该位置 |
| `src/*.py` | 锚定且 `*` 不跨目录分隔符 |

## 启动方式

需要 Python 3.7+（开发与验收使用 3.9），无需安装任何依赖即可运行：

```bash
# 方式一：作为模块运行（推荐）
python3 -m minigit init
python3 -m minigit add .
python3 -m minigit commit -m "initial commit"
python3 -m minigit log --oneline

# 方式二：直接使用启动脚本
python3 bin/minigit status
# 或（具备执行权限时）
./bin/minigit status
```

作者信息默认 `minigit <minigit@example.com>`，可用环境变量覆盖
（便于复现，与 git 变量同名兼容）：

```bash
MINIGIT_AUTHOR_NAME / MINIGIT_AUTHOR_EMAIL / MINIGIT_AUTHOR_DATE
GIT_AUTHOR_NAME / GIT_AUTHOR_EMAIL / GIT_AUTHOR_DATE / GIT_COMMITTER_*
```

## 运行测试

```bash
python3 -m pytest tests/ -v
```

全部测试都在 pytest 的 `tmp_path` 临时目录中进行（自动 chdir），
不会污染运行环境。覆盖点包括：

- 对象 SHA-1 稳定性（手工拼帧比对）、blob 去重（两个同内容文件指向同一对象、
  磁盘只有一份松散对象）；
- tree 递归与 git 风格排序的确定性（与插入顺序无关）；
- add / commit / log 的父子提交链与作者/日期/消息；
- branch / checkout 的新增、覆盖、删除三情形，未跟踪文件保留与覆盖保护；
- status 三态、staged 删除与工作区 deleted 区分；
- diff 的增删改、调换两行、`--cached`、整文件删除与 `--stat`；
- `.minigitignore` 的 `* ? / 前导斜杠 多段锚定` 匹配逻辑；
- reset `--soft` / `--mixed`（默认）语义与无效引用报错；
- 未 init 目录下所有命令的明确错误、未知子命令、缺参数、未知分支、未知提交；
- 空提交约定（首提交空索引用 `--allow-empty`，无改动普通 commit 报错且一致）；
- 3 MiB 大文件 add/commit 不卡死且字节一致。

## 代码组织

```text
minigit/
├── __init__.py      包说明
├── __main__.py      python -m minigit 入口
├── cli.py           参数入口与子命令分发、退出码
├── errors.py        MiniGitError 体系（面向用户的错误都走这里）
├── repository.py    仓库发现/初始化与目录布局
├── objects.py       对象库：blob/tree/commit，SHA-1 + zlib，读写 API
├── index.py         二进制索引序列化/反序列化与增删
├── refs.py          HEAD、refs/heads、分支校验、引用（含短 hash）解析
├── ignore.py        .minigitignore 解析、glob 匹配、工作区遍历剪枝
├── worktree.py      流式写 blob、文件模式、checkout 还原/删除/建目录
├── status.py        staged / modified / untracked / deleted 状态计算
├── diff.py          LCS、unified diff、--stat
└── commands.py      init/add/commit/log/branch/checkout/status/diff/reset
bin/minigit          独立启动脚本（薄封装）
tests/               pytest 测试与 conftest 夹具
```

## 设计约定（空提交等边界）

- **空提交**：索引树与 HEAD 树一致时，`commit` 输出
  `nothing to commit, working tree clean ...`，退出码 1；
  尚无提交时空索引同样报错，除非显式 `--allow-empty`（允许首个空提交）。
- **无 parent**：仓库第一个提交没有 `parent` 行；`log` 沿首 parent 走到根即止。
- **错误退出码**：任何面向用户的错误（未 init、未知子命令、缺参数、未知提交/分支、
  checkout 将覆盖未跟踪文件等）都打印明确信息到 stderr 并以 **1** 退出；成功为 0。
- **符号链接**：不支持，对链接执行 `add` 会明确报错。
- **大文件**：`add` 以 1 MiB 分块流式计算 SHA-1 并同步 zlib 压缩，
  全程不把整文件读入内存。
