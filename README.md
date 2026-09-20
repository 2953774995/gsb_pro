# cfgvault

`cfgvault` 是一个只使用 Python 标准库实现的连锁零售促销配置快照与版本管理工具。它面向一个工作目录中的多棵配置树（商品价格、折扣规则、海报文案等），支持在「日常版 / 大促版 / 会员日版」等多套方案之间切换、比较差异，并可回滚到历史快照。

项目不依赖任何第三方运行时依赖；测试仅使用 `pytest`，被测代码也不会通过 `subprocess` 调用外部命令。

## 环境要求

- Python 3.9 或更高版本（仅标准库）
- 测试：`pytest`

## 快速开始

在项目根目录或设置好 `PYTHONPATH` 后运行：

```bash
python3 -m cfgvault init
python3 -m cfgvault add prices discounts posters
python3 -m cfgvault snap -m "日常版基线"
python3 -m cfgvault log --oneline
```

创建、切换方案：

```bash
python3 -m cfgvault branch 大促版
python3 -m cfgvault checkout 大促版
# 修改配置后
python3 -m cfgvault add .
python3 -m cfgvault snap -m "双十一大促版"
python3 -m cfgvault checkout main
```

查看状态与差异：

```bash
python3 -m cfgvault status
python3 -m cfgvault status --short
python3 -m cfgvault diff
python3 -m cfgvault diff --cached
python3 -m cfgvault diff --stat
python3 -m cfgvault diff <快照A> <快照B>
```

回滚：

```bash
# 只移动当前方案指针，工作区和索引不变
python3 -m cfgvault reset --soft <snapshot>

# 移动指针并把索引重置为目标快照；工作区内容保留
python3 -m cfgvault reset --mixed <snapshot>
```

运行测试：

```bash
python3 -m pytest tests/ -v
```

所有 pytest 用例都在 `tmp_path` 临时目录中执行，不会污染运行目录。

## 仓库目录结构

```text
.cfgvault/
├── HEAD                 # 当前方案名，例如：大促版
├── index                # 稳定、可复现的 JSON 索引
├── objects/             # SHA-1 内容寻址对象库
│   └── xx/
│       └── <后 38 位 hash>
└── refs/
    └── heads/
        ├── main
        ├── 大促版
        └── 会员日版
```

默认方案名为 `main`，分支文件为空表示该方案尚未产生快照。

## 对象格式

所有对象都使用 SHA-1 内容寻址，哈希输入包含类型和长度头：

```text
<type> <payload length>\n
<payload bytes>
```

对象文件保存的是上述字节的 zlib 压缩数据，路径为：

```text
.cfgvault/objects/<hash 前 2 位>/<hash 后 38 位>
```

读取对象时会重新计算哈希并校验长度，损坏或路径名与内容不一致会报错。

### blob

- 类型：`blob`
- payload：配置文件的原始字节
- 相同内容只保存一个对象；重复 `add` 不会产生新 blob

内部 API：

- `cfgvault.objects.write_blob_bytes(root, data)`
- `cfgvault.objects.write_blob_file(root, source)`：按块写入数 MB 文件
- `cfgvault.objects.read_blob(root, oid)`
- `cfgvault.objects.write_object(root, object_type, payload)`
- `cfgvault.objects.read_object(root, oid)`

### tree

- 类型：`tree`
- 从索引递归构建，保存目录和文件的 `模式 / 名字 / hash` 三元组
- 文件按 UTF-8 字节序排序，空树也是一个可复用对象
- 目录模式为 `40000`，普通文件通常为 `100644`，可执行文件为 `100755`

每行格式：

```text
<mode> <name>\t<sha-1>
```

示例：

```text
40000 discounts	1111111111111111111111111111111111111111
40000 posters	2222222222222222222222222222222222222222
100644 prices.json	3333333333333333333333333333333333333333
```

内部 API：

- `cfgvault.trees.build_tree(root, entries)`
- `cfgvault.trees.read_tree(root, tree_oid)`
- `cfgvault.trees.serialize_tree(entries)`
- `cfgvault.trees.parse_tree(payload)`

### snapshot

- 类型：`snapshot`
- payload 为带排序键、缩进和末尾换行的确定性 JSON
- `parent` 指向上一个快照；首个快照的 `parent` 为 `null`
- 方案分支每次 `snap` 后自动推进到新快照

字段：

```json
{
  "version": 1,
  "tree": "<root tree sha-1>",
  "parent": "<parent snapshot sha-1 or null>",
  "operator": "operator <operator@local>",
  "date": "2026-09-21T10:00:00+08:00",
  "message": "日常版基线"
}
```

操作人默认来自 `CFGVAULT_OPERATOR`、`GIT_AUTHOR_NAME`、`USER` 或 `LOGNAME`；邮箱可由 `CFGVAULT_EMAIL` 或 `GIT_AUTHOR_EMAIL` 覆盖。

## 索引格式

`.cfgvault/index` 是稳定 JSON，路径按 UTF-8 字节序排序：

```json
{
  "version": 1,
  "entries": [
    {
      "blob": "0123456789abcdef0123456789abcdef01234567",
      "mode": "100644",
      "path": "prices/drinks.json"
    }
  ]
}
```

同一份索引重复序列化产生相同字节；索引写入采用临时文件原子替换。

## 命令清单

| 命令 | 说明 |
| --- | --- |
| `init [path]` | 创建 `.cfgvault/objects`、`.cfgvault/refs/heads`、空索引和 HEAD |
| `add <path>...` | 写 blob 并注册到索引；支持文件和目录；已跟踪文件不存在时暂存删除 |
| `snap -m <msg>` | 从索引构建 tree 和 snapshot，parent 指向当前 HEAD |
| `snap --allow-empty -m <msg>` | 即使索引与 HEAD 相同也创建显式空变化快照 |
| `log` | 沿 parent 链输出 hash、操作人、日期、说明 |
| `log --oneline` | 输出 8 位短 hash 与首行说明 |
| `branch` | 列出方案，当前方案前缀为 `*` |
| `branch <方案名>` | 在当前 HEAD 创建方案，不切换工作区 |
| `checkout <方案名>` | 切换 HEAD，并还原工作区与索引到目标快照 |
| `status` | 输出 staged、modified、untracked、deleted |
| `status --short` | 紧凑格式，如 `A  x`、`M  x`、` M x`、` D x`、`?? x` |
| `diff` | 默认比较工作区与索引 |
| `diff --cached` | 比较索引与 HEAD |
| `diff --head` | 比较工作区与 HEAD |
| `diff <ref>` | 比较工作区与指定快照/方案 |
| `diff <refA> <refB>` | 比较两个快照或方案 |
| `diff --stat ...` | 输出每个文件增删行统计 |
| `reset --soft <ref>` | 仅移动当前方案指针 |
| `reset --mixed <ref>` | 移动指针并把索引重置到目标快照，工作区不动 |

引用可以是方案名、完整 40 位快照 hash，或长度至少 4 位且无歧义的 hash 前缀。

### 空快照约定

默认情况下，如果索引内容与当前 HEAD 对应的 tree 完全相同，`snap` 不创建新对象并输出：

```text
No changes staged; snapshot not created
```

这样重复执行同内容 `add` + `snap` 不会制造空提交噪音。运营若需要显式记录“再次确认/发布”操作，可使用：

```bash
python3 -m cfgvault snap --allow-empty -m "再次确认日常版"
```

在尚未有快照且索引为空时，默认同样不创建快照。

## checkout 语义

切换方案时：

1. 删除旧索引中存在、目标快照中不存在的已跟踪文件；
2. 覆盖两者都跟踪的文件内容和模式；
3. 新增目标快照中的文件和目录；
4. 不处理未跟踪文件，未跟踪文件会保留；
5. 如果未跟踪文件会被目标文件覆盖，命令报错并终止，避免误删本地改动；
6. 索引最终重置为目标快照。

## status 状态含义

- `staged` / 紧凑输出第一列：索引相对 HEAD 新增、修改或删除；
- `modified`：工作区文件内容或模式与索引不同；
- `deleted`：文件在索引中存在，但工作区已删除；
- `untracked`：工作区存在但索引中没有；
- 忽略文件既不会被 `add .` 加入，也不会出现在普通 `status` 中。

## unified diff 说明

`diff` 使用标准库 `difflib.SequenceMatcher` 生成行级 opcodes，再输出简化 unified diff：

- `@@ -old_start,old_count +new_start,new_count @@` 定位；
- `-` 表示旧文件删除行，`+` 表示新文件新增行，空格前缀表示上下文；
- 默认上下文为 3 行；
- 对调换两行的情况，会如实显示一组删除/新增；
- `--stat` 统计每个文件的新增行、删除行和变更文件总数；
- UTF-8 之外或包含 NUL 的内容显示 `Binary files differ`，不计入行级增删。

## .cfgvaultignore

仓库根目录可放 `.cfgvaultignore`。支持的基础规则：

- `*` 匹配除 `/` 外的任意字符序列；
- `?` 匹配除 `/` 外的一个字符；
- `foo.tmp`：无 `/` 时可匹配任意深度的同名文件或目录；
- `/foo.tmp`：只匹配仓库根目录；
- `poster/local.txt`：包含 `/`，从仓库根目录锚定；
- `cache/`：尾部 `/` 表示只匹配目录，遍历时可直接裁剪该目录；
- 空行和以 `#` 开头的行是注释。

`.cfgvault` 元数据目录永不进入索引；`.git` 目录同样不会被扫描或跟踪。已经跟踪的文件即使后来匹配 ignore 规则，仍会在 `status` 中显示修改或删除，避免忽略规则隐藏已纳管配置的异常。

## 错误处理与退出码

- 成功：退出码 `0`
- 未 init、路径不存在、非法快照引用、checkout 不存在方案、未跟踪文件冲突等：退出码 `1`，输出 `error: ...`
- 缺少参数、未知子命令等 argparse 参数错误：退出码 `2`
- 快照引用不存在、过短或前缀歧义均会给出明确错误

## 代码组织

```text
cfgvault/
├── __init__.py
├── __main__.py        # python -m cfgvault 入口
├── cli.py             # argparse 命令分发
├── commands.py        # 各子命令业务编排
├── objects.py         # blob/tree/snapshot 对象库、zlib、SHA-1
├── trees.py           # tree 三元组、递归构建与展开
├── index.py           # 稳定 JSON 索引与原子写入
├── refs.py            # HEAD、方案分支引用
├── snapshots.py       # snapshot 元数据与引用解析
├── workspace.py       # 文件遍历、add、checkout 工作区还原
├── ignore.py          # .cfgvaultignore glob 规则
├── diff.py            # unified diff 与 --stat
├── repository.py      # 仓库发现、初始化和高层 facade
└── errors.py          # 用户可见错误类型
```

## 设计约束

- 不使用 `subprocess`、shell 或任何外部 VCS；
- 运行时代码只 import Python 标准库；
- 大文件 blob 以 1 MiB 分块计算和压缩写入，避免一次性占用数倍内存；
- 对象、tree、索引均采用确定性排序和稳定序列化；
- 所有写文件操作尽量通过临时文件 + 原子替换完成。
