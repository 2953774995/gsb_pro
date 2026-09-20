# cfgvault — 促销配置快照与版本管理

`cfgvault` 是一个仅使用 **Python 标准库** 实现的轻量级配置版本管理工具，面向连锁零售总部的促销配置目录：商品价格、折扣规则、海报文案等多棵 JSON/文本配置树都可以建立快照、在多套方案之间切换、对比差异，并在误改后回滚。

- 运行时代码不依赖任何第三方包，也不调用 `subprocess` 或外部命令。
- 对象库、索引、引用、工作区还原、diff、命令分发和 CLI 分层实现。
- 测试使用 `pytest`，全部在临时目录中运行。

## 目录结构

```text
.cfgvault/
├── HEAD                 # 当前方案名，例如 main
├── index                # 暂存索引：路径、模式、blob hash
├── objects/             # 内容寻址对象库
│   └── xx/              # SHA-1 前两位作为目录
│       └── 38...        # SHA-1 后 38 位作为文件名
└── refs/
    └── heads/
        ├── main
        ├── daily
        ├── promo
        └── member-day
```

## 对象格式

所有对象均以 SHA-1 内容寻址，并使用 zlib 压缩落盘：

```text
SHA-1(object_type + NUL + content)
```

磁盘中保存的是：

```text
zlib.compress(object_type + NUL + content)
```

因此对象路径固定为：

```text
.cfgvault/objects/<hash 前 2 位>/<hash 后 38 位>
```

支持三种对象：

### 1. blob：配置文件内容

`content` 是文件的原始字节，不额外加 JSON 包装。相同内容的文件共享同一个 blob，因此重复 `add`、重复 `snap` 都不会产生重复 blob。

```text
blob\0<原始文件字节>
```

blob 文件按 1 MiB 分块计算 SHA-1 和压缩，数 MB 配置文件不需要整体多次读入内存。

### 2. tree：目录树

tree 记录有序的 `模式 / 名字 / hash` 三元组，递归构建目录结构。模式包括：

- `100644`：普通文件；
- `100755`：可执行文件；
- `40000`：子目录。

文本序列化格式为每行一条记录：

```text
<mode>\t<name>\t<object-sha1>
```

示例：

```text
40000	discount	c892...
100644	prices.json	9f31...
40000	poster	1d7a...
```

tree 条目始终按名字排序，目录从最深层向上构建；同一个索引无论以什么遍历顺序加入，根 tree hash 都完全一致。空 tree 是空内容：

```text
tree\0
```

### 3. snapshot：快照

snapshot 保存 tree、父快照、操作人、日期和说明：

```text
tree <tree-sha1>
[parent <parent-snapshot-sha1>]
author <操作人>
date <日期与时区>

<快照说明，可多行>
```

第一个快照没有 `parent` 行；后续快照的 `parent` 指向当前方案原来的 HEAD。

> 空快照约定：即使索引中没有任何文件，也允许执行 `snap -m ...`。该快照会指向固定 hash 的空 tree，因此“建立空基线”的行为是显式且一致的；后续快照仍可记录 parent、操作人、日期和说明。

## 索引格式

索引文件为稳定、可复现的版本化二进制/文本混合格式：

```text
CFGVLTIDX
1
<mode>\t<blob-sha1>\t<posix/path>
...
```

路径使用 POSIX `/`，记录始终按路径排序。例如：

```text
CFGVLTIDX
1
100644	3ffe6a...	config/price.json
100644	105898...	poster/title.txt
```

## 引用与方案

- `.cfgvault/HEAD`：保存当前方案名；
- `.cfgvault/refs/heads/<方案名>`：保存该方案当前 snapshot 的 40 位 SHA-1；
- `snap` 只推进当前方案；
- `branch <name>` 从当前 HEAD 创建方案，但不自动切换；
- `checkout <name>` 切换 HEAD，并把该方案快照还原到工作区。

checkout 规则：

1. 删除旧方案已跟踪、但目标方案不存在的文件；
2. 覆盖两个方案都跟踪的文件；
3. 创建目标方案新增的文件；
4. 不在旧索引中、也不在目标 tree 中的文件视为未跟踪文件，保留；
5. 如果目标路径会覆盖一个现存未跟踪文件，为避免数据丢失，报错并返回非零状态码；
6. `.cfgvault` 元数据目录永不进入索引，也不会被还原。

## 支持命令

### init

```bash
python3 -m cfgvault init [path]
```

初始化 `.cfgvault/objects/`、`.cfgvault/refs/heads/`、`.cfgvault/HEAD` 和空索引。默认分支为 `main`。重复初始化不会覆盖已有对象、索引或引用。

### add

```bash
python3 -m cfgvault add <path> [<path> ...]
```

- 文件：写入 blob，并把 `路径/模式/hash` 注册到索引；
- 目录或 `.`：递归添加；
- 已删除的显式文件路径：从索引移除，即暂存删除；
- 相同内容只生成一个 blob；
- 匹配 `.cfgvaultignore` 的路径会跳过；
- `.cfgvault` 始终跳过。

### snap

```bash
python3 -m cfgvault snap -m "大促方案 2026-09-21"
```

从当前索引递归构建 tree，再创建 snapshot 并推进当前方案引用。

操作人和日期可通过环境变量固定，方便审计或自动化测试：

```bash
CFGVULT_AUTHOR_NAME="Alice" \
CFGVULT_AUTHOR_EMAIL="alice@example.com" \
CFGVULT_AUTHOR_DATE="2026-09-21 10:00:00 +0800" \
python3 -m cfgvault snap -m "会员日方案"
```

`CFGVULT_AUTHOR_DATE` 也可以是 Unix 时间戳字符串。

### log

```bash
python3 -m cfgvault log
python3 -m cfgvault log --oneline
```

沿 parent 链输出快照：完整格式包含 hash、操作人、日期、说明；`--oneline` 输出短 hash 加首行说明。

### branch

```bash
python3 -m cfgvault branch
python3 -m cfgvault branch promo
```

无参列出方案，当前方案前缀为 `*`；带名称时在当前 HEAD 创建方案。

### checkout

```bash
python3 -m cfgvault checkout promo
python3 -m cfgvault checkout member-day
```

切换当前方案并还原对应工作区。未跟踪文件保留，已跟踪文件会按目标快照覆盖或删除。

### status

```bash
python3 -m cfgvault status
python3 -m cfgvault status --short
```

状态分为：

- `staged` / `A`、`M`、`D`：索引与 HEAD 不同；
- `modified` / `M`：工作区与索引不同；
- `deleted` / `D`：工作区文件被删除；
- `untracked` / `??`：不在索引中；
- 被忽略的未跟踪文件默认不显示。

### diff

```bash
# 默认：工作区 vs 索引（包含未跟踪的非忽略文件）
python3 -m cfgvault diff

# 索引 vs HEAD
python3 -m cfgvault diff --cached

# 工作区 vs 指定快照
python3 -m cfgvault diff <snapshot>

# 两个快照互相对比
python3 -m cfgvault diff <snapshot-a> <snapshot-b>

# 文件级增删统计
python3 -m cfgvault diff --stat
python3 -m cfgvault diff --cached --stat
```

输出简化 unified diff：包含文件头、`@@` hunk 定位、3 行上下文、行级 `-`/`+`。二进制文件只提示不同，不尝试文本化。

`--stat` 示例：

```text
prices.json |    4  +2 -2 ++--
rules.json  |    1  +1 -0 +
2 files changed, 3 insertion(s)(+), 2 deletion(s)(-)
```

### reset

```bash
python3 -m cfgvault reset --soft <snapshot>
python3 -m cfgvault reset --mixed <snapshot>
```

- `--soft`：只移动当前方案指针；工作区和索引均不改变；
- `--mixed`：移动当前方案指针，并把索引重置为该快照的 tree；工作区不改变，因此之后 `status`/`diff` 可查看工作区相对旧快照的差异。

`<snapshot>` 可以是：

- `HEAD`；
- 方案名；
- 40 位完整对象 hash；
- 至少 4 位且唯一的短 hash。

无效快照引用、不存在方案、缺少参数、未知命令、未 init 等错误都会输出明确错误并返回非零退出码。

## .cfgvaultignore

在工作区根目录放置 `.cfgvaultignore`，支持基础 glob：

```gitignore
# 任意目录下匹配后缀
*.tmp
*.log

# 单字符匹配
draft?.txt

# 只匹配根目录文件
/fixed.txt

# 带 / 的路径从根目录匹配
nested/*.json

# 目录及其所有内容
cache/
build/output/
```

规则说明：

- `*` 匹配任意数量字符，但不跨 `/`；
- `?` 匹配单个非 `/` 字符；
- `[abc]` 字符类也可使用；
- 前导 `/` 表示锚定仓库根目录；
- 结尾 `/` 表示目录；
- `.cfgvault` 元数据目录无论是否编写规则都永不进入索引。

`.cfgvaultignore` 文件本身可以被跟踪；已经跟踪的文件即使后来匹配忽略规则，仍会继续在状态中可见，避免已纳入版本管理的配置被静默隐藏。

## 快速上手

```bash
mkdir promotion-configs
cd promotion-configs
python3 -m cfgvault init

mkdir prices poster discount
printf '{"sku": 1, "price": 100}' > prices/sku-1.json
printf '满 100 减 20' > discount/rules.txt
printf '秋季大促' > poster/title.txt

python3 -m cfgvault add .
python3 -m cfgvault snap -m "日常版"

python3 -m cfgvault branch promo
python3 -m cfgvault checkout promo
printf '{"sku": 1, "price": 80}' > prices/sku-1.json
python3 -m cfgvault add .
python3 -m cfgvault snap -m "大促版"

python3 -m cfgvault diff main promo --stat
python3 -m cfgvault checkout main
python3 -m cfgvault log --oneline
```

> 上面的 `python3 -m cfgvault` 需要在项目根目录执行，或把项目根目录加入 `PYTHONPATH`。仓库没有安装外部 console script，因为目标环境禁止安装外部软件。

## 运行测试

在项目根目录执行：

```bash
python3 -m pytest tests/ -v
```

测试覆盖：

- 对象 hash 稳定性、zlib 对象落盘和 blob 去重；
- tree 递归构建、顺序确定性和空 tree；
- 索引稳定复现；
- `add` / `snap` / `log` 的快照链和 parent；
- `branch` / `checkout` 的新增、覆盖、删除、未跟踪保留；
- `status` 的 staged、modified、deleted、untracked；
- unified diff、调换行内容、新增/删除和 `--stat`；
- `.cfgvaultignore` glob 匹配；
- `reset --soft` 与 `reset --mixed`；
- 未 init、缺参数、未知命令、不存在快照/方案的非零退出码；
- 空快照；
- 数 MB 大文件分块 add/snap；
- 运行时代码仅使用标准库，且不包含 `subprocess`/外部命令调用。

## 模块职责

```text
cfgvault/
├── cli.py        # argparse 参数解析、错误码和命令分发
├── commands.py   # 高层子命令业务逻辑
├── repo.py       # 仓库发现、init、路径管理
├── objects.py    # blob/tree/snapshot 对象库、SHA-1、zlib、tree 递归
├── index.py      # 稳定索引读写
├── refs.py       # HEAD、分支引用、hash 前缀解析
├── workspace.py  # add、工作区扫描、checkout 还原、status 比较
├── ignore.py     # .cfgvaultignore glob
├── diff.py       # unified diff 与 --stat
├── errors.py     # 用户可见错误类型
└── util.py       # 原子写、路径规范化等工具
```
