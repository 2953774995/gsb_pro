# minigit

一个用 **Python 标准库** 从零实现的迷你版 Git 版本控制核心，不依赖任何第三方包
（测试框架 pytest 除外），也不通过 subprocess 调用 git 或任何外部命令。

## 运行环境

- Python 3.6+（仅标准库：`hashlib` / `zlib` / `json` / `argparse` / `difflib` / `fnmatch` 等）
- 运行测试需要 `pytest`

## 启动方式

```bash
# 在任意目录下（把项目根目录加入 PYTHONPATH，或直接在项目根目录运行）
python3 -m minigit <command> [args]

# 也可以配置一个别名方便使用
alias minigit="PYTHONPATH=/path/to/project python3 -m minigit"
```

## 快速上手

```bash
python3 -m minigit init                 # 创建 .minigit 仓库
echo "hello" > a.txt
python3 -m minigit add a.txt            # 写入 blob 并登记到索引
python3 -m minigit commit -m "initial"  # 从索引构建 tree/commit，推进当前分支
python3 -m minigit log --oneline        # 短 hash + 首行消息
python3 -m minigit branch feature       # 在当前 HEAD 创建分支
python3 -m minigit checkout feature     # 切换分支并还原工作区
python3 -m minigit status --short       # 紧凑状态输出
python3 -m minigit diff                 # 工作区 vs 索引（unified diff）
python3 -m minigit reset --mixed HEAD   # 重置索引到指定提交
```

## 支持命令清单

| 命令 | 说明 |
| --- | --- |
| `init [path]` | 创建 `.minigit` 目录结构（objects、refs/heads、HEAD），默认分支 `main` |
| `add <path>...` | 写入 blob、登记索引；目录递归添加并同步其下的删除；跳过忽略文件 |
| `commit -m <msg>` | 从索引构建 tree 与 commit，parent 指向当前 HEAD，自动推进当前分支 |
| `log [--oneline]` | 沿 parent 链打印提交（hash/作者/日期/消息），`--oneline` 为短格式 |
| `status [--short]` | 三态输出：staged / modified(unstaged) / untracked，能区分 deleted |
| `diff [--cached] [--stat]` | 默认工作区 vs 索引；`--cached` 为索引 vs HEAD；`--stat` 为增删行统计 |
| `branch [name]` | 无参列出分支（当前分支打 `*`）；有参在当前 HEAD 创建分支 |
| `checkout <branch>` | 切换 HEAD 并还原工作区（恢复/覆盖/删除已跟踪文件，保留未跟踪文件） |
| `reset [--soft\|--mixed] <commit>` | `--soft` 仅移动分支指针；`--mixed`（默认）再重置索引。commit 可为分支名、`HEAD`、完整或缩写 sha |

**空提交约定**：暂存区与 HEAD 完全一致时 `commit` 输出 `nothing to commit` 并以
退出码 1 拒绝，不产生新提交（行为固定一致）。

## 存储格式

### 对象库（`.minigit/objects/`）

- 对象 id = `sha1("<type> <size>\0" + payload)`，与 Git 一致；
- 磁盘内容为 `zlib` 压缩的 `<type> <size>\0<payload>`；
- 路径为 `.minigit/objects/<sha 前 2 位>/<sha 后 38 位>`；
- 内容寻址天然去重：相同内容的 blob 只存储一次。

三种对象类型：

- **blob**：文件原始字节；
- **tree**：若干 `mode name\0<20 字节二进制 sha>` 记录，按 Git 规则排序
  （目录按 `name/` 参与排序），递归构建；mode 为 `100644` / `100755` / `40000`；
- **commit**：文本格式

  ```
  tree <sha>
  parent <sha>            # 首提交无此行
  author Name <email> <unix-ts> <tz>
  committer Name <email> <unix-ts> <tz>

  <message>
  ```

作者信息取自环境变量 `MINIGIT_AUTHOR_NAME` / `MINIGIT_AUTHOR_EMAIL`，缺省为
`minigit <minigit@example.com>`。

### 索引（`.minigit/index`）

UTF-8 JSON 文件，条目按路径排序，保证稳定可复现：

```json
{
  "version": 1,
  "entries": [
    {"path": "a.txt", "mode": "100644", "hash": "<blob sha1>"}
  ]
}
```

### 引用

- `.minigit/HEAD`：`ref: refs/heads/<branch>`（或分离头指针时直接为 commit sha）；
- `.minigit/refs/heads/<branch>`：内容为该分支指向的 commit sha；
- `commit` 自动推进 HEAD 指向的分支引用。

### 忽略规则（`.minigitignore`）

- `*`、`?` 通配；`*.log` 匹配任意层级；
- `build/` 仅匹配目录（其下所有内容被忽略）；
- `docs/*.md` 等含 `/` 的模式按仓库相对路径匹配；
- 空行与 `#` 注释被忽略；`.minigit` 目录自身永不进入索引。

## 代码结构

```
minigit/
  cli.py         # argparse 参数解析与命令分发，统一错误处理与退出码
  commands.py    # 各子命令实现（init/add/commit/log/status/diff/branch/checkout/reset）
  repository.py  # 仓库发现（向上查找 .minigit）与初始化
  objects.py     # 对象库：sha1 寻址、zlib 读写、tree/commit 编解码
  index.py       # 索引读写（JSON，稳定可复现）
  refs.py        # HEAD 与分支引用管理
  workspace.py   # 工作区遍历、checkout 还原
  ignore.py      # .minigitignore glob 匹配
  diffutil.py    # unified diff 生成与增删行统计（difflib）
  errors.py      # 统一的用户可见异常
tests/           # pytest 测试（全部在临时目录中运行）
```

## 错误处理

缺少参数、未知子命令、未 `init` 的目录、不存在的提交引用、checkout 不存在的
分支等情况都会向 stderr 输出明确错误信息并返回非零退出码。

## 运行测试

```bash
python3 -m pytest tests/ -v
```

测试覆盖：对象哈希稳定性与 blob 去重、tree 构建顺序确定性、add/commit/log
提交链父子关系、branch/checkout 工作区还原（新增/覆盖/删除三情形）、status
三态与 deleted、diff 增删改与调换行、`.minigitignore` 匹配、reset 两种模式、
未 init 目录报错、空提交约定、数 MB 大文件 add/commit。全部测试在 pytest
`tmp_path` 临时目录中进行，不污染运行环境。
