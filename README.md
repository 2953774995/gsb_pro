# minigit

一个用 **Python 标准库** 从零实现的迷你版 Git 版本控制核心：内容寻址对象库、
索引（暂存区）、分支引用与常用子命令。除测试框架 pytest 外**不依赖任何第三方包**，
也**不通过 subprocess 调用 git 或任何外部命令**。

## 启动方式

```bash
# 在任意目录下（把仓库根目录加入 PYTHONPATH，或在本仓库根目录运行）
python3 -m minigit <command> [args]

# 也可以安装为可执行脚本（可选）
alias minigit="python3 -m minigit"
```

## 支持命令清单

| 命令 | 说明 |
| --- | --- |
| `minigit init [path]` | 创建 `.minigit` 目录结构（objects、refs/heads、HEAD、index） |
| `minigit add <path>...` | 将文件写入 blob 对象并注册到索引（支持目录递归，遵守忽略规则） |
| `minigit commit -m <msg>` | 从索引构建 tree 与 commit 对象，parent 指向当前 HEAD，并推进当前分支 |
| `minigit log [--oneline]` | 沿 parent 链打印提交（hash/作者/日期/消息），`--oneline` 为短 hash + 首行消息 |
| `minigit branch [name]` | 无参列出分支（当前分支打 `*`）；带名在当前 HEAD 创建分支 |
| `minigit checkout <branch>` | 切换 HEAD 并还原工作区：删除目标提交中不存在的已跟踪文件、覆盖已跟踪文件内容，未跟踪文件保留 |
| `minigit status [--short]` | 三态输出：staged（索引 vs HEAD）、modified/deleted（工作区 vs 索引）、untracked |
| `minigit diff [--cached] [--stat] [commit]` | 默认工作区 vs 索引；`--cached` 索引 vs HEAD；`commit` 工作区 vs 指定提交；`--stat` 输出增删行数统计 |
| `minigit reset --soft <commit>` | 仅移动当前分支指针，工作区与索引不动 |
| `minigit reset --mixed <commit>` | 移动分支指针并把索引重置为指定提交（工作区不动） |

**空提交约定**：暂存内容相对上一次提交没有任何变化时，`commit` 拒绝创建空提交，
输出 `nothing to commit` 并以非零码退出（行为一致、可预期）。

**错误处理**：缺少参数 / 未知子命令 / 未 init / 不存在的提交引用 / checkout 不存在的
分支等都会向 stderr 输出明确错误并返回非零退出码。

## 存储格式

### 对象库（`.minigit/objects/`）

- 三种对象类型：`blob`（文件内容）、`tree`（目录）、`commit`（提交）。
- 对象身份 = `SHA-1("<type> <长度>\0<内容>")`（与 Git 相同的分帧方式）。
- 对象内容经 **zlib 压缩**后写入 `objects/<哈希前2位>/<哈希后38位>`；
  内容寻址天然去重——同一内容的 blob 多次 add 只产生一个对象。
- **tree 对象**：若干 `(模式, 名字, hash)` 三元组的二进制序列
  `"<mode> <name>\0<20字节二进制sha>"`，按 Git 规则排序（目录按 `name/` 参与排序），
  保证构建顺序确定性；子目录递归构建为子 tree 对象。
- **commit 对象**：文本格式

  ```
  tree <tree-hash>
  parent <parent-hash>        # 首提交无此行
  author Name <email> <epoch> <tz>
  committer Name <email> <epoch> <tz>

  <message>
  ```

### 索引（`.minigit/index`）

纯文本、按路径排序、稳定可复现，每行一条记录：

```
<mode> <blob-sha1> <路径>
```

### 引用

- `.minigit/HEAD`：`ref: refs/heads/<branch>`（当前分支名）。
- `.minigit/refs/heads/<branch>`：内容为该分支指向的 commit hash。
- `commit` 自动推进当前分支；`reset` 移动分支指针；`checkout` 切换 HEAD。

### 忽略规则（`.minigitignore`）

支持基础 glob：`*`、`?`、`[...]`；`dir/` 仅匹配目录；含 `/` 的模式锚定仓库根；
`!` 取反；`#` 注释。`.minigit` 目录自身永不进入索引。`add` 与 `status` 均跳过匹配文件。

## 运行测试

```bash
python3 -m pytest tests/ -v
```

全部测试在 pytest 临时目录（`tmp_path`）中进行，不污染运行环境。覆盖：对象哈希
稳定性与 blob 去重、tree 构建顺序确定性、add/commit/log 提交链、branch/checkout
工作区还原（新增/覆盖/删除三情形）、status 三态与 deleted、diff 增删改与换行、
`.minigitignore` 匹配、reset 两种模式、未 init 目录报错、空提交约定、大文件 add 等。

## 代码组织

```
minigit/
  cli.py       # argparse 参数解析、子命令分发、错误处理与退出码
  commands.py  # 各子命令实现（init/add/commit/log/branch/checkout/status/diff/reset）
  repo.py      # 仓库发现与 .minigit 目录布局、init
  objects.py   # 对象库：hash/write/read、tree 序列化/解析/递归展开
  index.py     # 索引读写、从索引递归构建 tree
  refs.py      # HEAD/分支引用管理与 revision 解析（HEAD/分支名/短哈希）
  ignore.py    # .minigitignore 匹配
  diff.py      # 简化 unified diff 与增删统计（difflib）
  errors.py    # MiniGitError（携带退出码）
tests/         # pytest 测试
```
