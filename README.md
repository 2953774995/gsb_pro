# kbsearch — 离线售后知识库检索工具

`kbsearch` 面向售后工程师上门维修时的离线场景，可在没有网络的笔记本电脑上检索维修手册、历史工单等一批 UTF-8 文本文件。项目**只使用 Python 标准库**；测试使用 `pytest`。

## 功能概览

- 文档管理：`add_document` / `remove_document` / `document_count`，`doc_id` 支持 `int` 和 `str`，同 ID 重复添加会覆盖旧文档。
- 中英文混合分析：英文按字母数字切词、小写化并应用简化词干化；中文按单个汉字切分，因此任意连续中文查询都能按字命中。
- 英文停止词：内置 `a/the/is/of/and/or` 等常见停止词，可在构造 `KBSearch(use_stopwords=False)` 时关闭。
- 倒排索引：保存每篇文档的词频 `tf`、位置列表、每词文档频率 `df`、每篇有效词数；删除文档会同步清理全部 postings。
- 查询语言：支持 `AND`、`OR`、`NOT`、括号、隐式 AND、短语查询 `"..."`、前缀查询 `term*`。
- TF-IDF：词频使用 `1 + log(tf)`，IDF 使用平滑公式 `log(1 + N/df)`；布尔结果同样按分数降序。
- 摘要：`with_snippet=True` 时返回命中位置附近、总计不超过 80 个字符的片段。
- 同义词：支持 `冰箱=冰柜=冷藏柜`、`维修=修理` 这类配置；自动扩展出的同义词组只取命中变体的最高分，不重复计数；显式写出的 `A OR B` 仍按用户表达式对两个独立词打分。
- 持久化：单个 JSON 索引文件保存文档、postings、统计信息和同义词；重启后直接加载即可查询。
- 增量更新：修改某一个 `.txt` 后只重建该文档的 postings，其他文档索引不动。
- CLI：支持批量建索引、交互式查询、`--reindex` 全量重建、`--update <file>` 单文件增量更新。

## 环境要求

- Python 3.8+（开发验证使用 Python 3.9）
- 运行时代码无第三方依赖
- 仅测试需要 `pytest`

## 快速开始

### 1. 批量建立索引

仓库内提供了一个示例目录：

```bash
./kbsearch-cli \
  --directory docs-corpus \
  --synonyms examples-synonyms.txt \
  --index .kbsearch/index.json
```

也可以使用模块方式启动：

```bash
python3 -m kbsearch --directory docs-corpus --synonyms examples-synonyms.txt
```

标题取每个 `.txt` 文件的第一个非空行；文件为空时退回文件名。目录中名为 `synonyms.txt` 的文件按配置处理，不会被当作维修手册建索引；未显式传 `--synonyms` 时会自动尝试加载该文件。

### 2. 执行一次布尔查询

```bash
./kbsearch-cli \
  --index .kbsearch/index.json \
  --query '压缩机 AND (异响 OR 不制冷) AND NOT 洗衣机'
```

输出示例字段：

```text
doc_id=refrigerator.txt score=14.060521
  冰箱压缩机异响维修手册 故障现象：冰箱运行时压缩机位置出现异响...
```

### 3. 交互式查询

不带 `--query` 时默认进入交互模式：

```bash
./kbsearch-cli --index .kbsearch/index.json
```

交互模式支持：

- 普通词：`压缩机`
- 布尔查询：`压缩机 AND (异响 OR 不制冷)`
- 排除：`压缩机 AND NOT 洗衣机`
- 短语：`"压缩机异响"`
- 英文前缀：`comp*`
- 中文前缀：`冰*`、`压缩*`
- `:help` 查看帮助，`:quit` 退出

### 4. 全量重建和增量更新

目录内容大幅调整后全量重建：

```bash
./kbsearch-cli --directory docs-corpus --reindex
```

某个文本文件修改后，只更新该文档：

```bash
./kbsearch-cli --update docs-corpus/refrigerator.txt
```

增量更新会先删除该文档旧 postings，再写入新 postings；旧词不会残留，新词立即可查。未更新的其他文档不需要重新扫描。

## 查询语法

| 语法 | 含义 | 示例 |
| --- | --- | --- |
| 空白 / 相邻词 | 隐式 AND | `压缩机 异响` |
| `AND` | 两侧都必须命中 | `压缩机 AND 异响` |
| `OR` | 任一侧命中即可 | `异响 OR 噪音` |
| `NOT` | 一元排除，优先级高于 AND/OR | `NOT 洗衣机` |
| `()` | 改变组合优先级 | `压缩机 AND (异响 OR 不制冷)` |
| `"..."` | 按位置验证相邻出现 | `"not cool"`、`"不制冷"` |
| `*` | 词尾前缀匹配 | `comp*`、`冰*` |

操作符大小写不敏感：`and`、`And`、`AND` 等价。普通英文词也大小写不敏感。

非法查询会抛出 `kbsearch.SearchError`（继承 `ValueError`）并带原因，例如：

- 空查询或只有标点/停止词
- 孤立的 `AND` / `OR`
- `AND` / `OR` 缺少操作数
- `NOT` 后没有表达式
- 括号不匹配、空括号
- 短语缺少结束引号
- 前缀 `*` 出现在词首或词中

## Python API

```python
from kbsearch import KBSearch

kb = KBSearch()

# doc_id 可以是 int 或 str；重复添加同一个 doc_id 会覆盖旧文档
kb.add_document(1, "冰箱压缩机异响，需要检查风扇。")
kb.add_document("ticket-2", "冰柜不制冷，压缩机长时间运行。")

# 同义词组：任一变体查询时自动扩展为 OR
kb.add_synonym_group(["冰箱", "冰柜", "冷藏柜"])

results = kb.search(
    "压缩机 AND (异响 OR 不制冷)",
    top_k=10,              # 0 表示返回全部
    with_snippet=True,
)
for item in results:
    print(item["doc_id"], item["score"], item["snippet"])

kb.remove_document(1)
assert kb.document_count() == 1

kb.save("kb-index.json")
restarted = KBSearch.load("kb-index.json")
print(restarted.search("冰柜", top_k=5))
```

结果结构：

```python
{"doc_id": "ticket-2", "score": 5.12345678, "snippet": "...命中附近 80 字符..."}
```

无命中、空索引上的合法查询均返回 `[]`。

## 分词和简化词干化

### 英文

1. 连续 ASCII 字母或数字形成一个 token，例如 `E123`、`42`。
2. 转为小写。
3. 应用保守的简化后缀规则，常见规则包括：
   - 复数：`repairs -> repair`、`boxes -> box`、`errors -> error`
   - `ies/sses`：`faulties -> faulty`、`classes -> class`
   - 进行时/过去式：`repairing -> repair`、`repaired -> repair`
   - 重复辅音：`running -> run`
   - 常见后缀：`ly`、`ness`、`ment`、`able`、`ible`、`ful`
4. 数字不做词干化。

这是为了可审计、可预测而设计的精简规则，不是完整 Porter Stemmer；索引和查询使用同一套规则。

### 中文

每个 CJK 汉字独立成一个 term，位置仍按原始文本顺序记录。例如 `压缩机异响` 产生 `压、缩、机、异、响`。连续中文查询会编译为基于位置的汉字短语，因此既能保证每个单字可查，也能避免任意散乱单字误命中。

### 停止词

默认停止词包含：

`a, an, and, are, as, at, be, been, but, by, for, if, in, into, is, it, no, not, of, on, or, such, that, the, their, then, there, these, they, this, to, was, will, with`。

停止词从普通 term postings 中排除，因此不会计入 `df`、文档长度和分数；但它们的位置会单独保存在 `stop_positions` 中，所以像 `"does not cool"` 这种包含停止词的短语仍能按原始相邻关系验证。构造时使用 `KBSearch(use_stopwords=False)` 可关闭。

## 打分规则

每个 term 在文档中的权重：

```text
tf_norm = 1 + log(tf)
idf     = log(1 + N / df)
weight  = tf_norm * idf
```

- `N`：当前文档总数
- `df`：包含该 term 的文档数
- `tf`：term 在当前文档出现次数
- 短语得分为其中不同有效 term 权重之和
- 同义词组视为同一个“概念”，同一文档中多个变体不会叠加重复计分
- `NOT` 只过滤文档，不贡献分数
- 分数相同时按类型和 `doc_id` 字符串确定性排序，保证结果稳定

## 同义词文件

每行一组，用 `=` 分隔；空行和 `#` 开头的行会被忽略：

```text
冰箱=冰柜=冷藏柜
维修=修理
异响=噪音
refrigerator=fridge=freezer
```

加载方式：

```python
kb.load_synonyms("synonyms.txt")
```

CLI 中使用 `--synonyms synonyms.txt`。同义词会经过与索引相同的规范化流程，因此英文大小写、常见后缀变化也能匹配。

## 索引文件格式

持久化文件是一个 UTF-8 JSON 对象，当前版本为 `2`：

```json
{
  "version": 2,
  "settings": {"use_stopwords": true},
  "documents": {
    "s\u001fdoc1": {
      "text": "文档原文",
      "title": "第一个非空行",
      "source": "/abs/path/doc1.txt",
      "mtime": 1726000000.0
    }
  },
  "doc_lengths": {"s\u001fdoc1": 12},
  "postings": {
    "压": {
      "s\u001fdoc1": {"tf": 1, "positions": [0]}
    }
  },
  "synonyms": {
    "groups": [[["冰", "箱"], ["冰", "柜"]]]
  }
}
```

说明：

- JSON 对象的键只能是字符串，所以内部 doc_id 键使用 `i\u001f<id>` / `s\u001f<id>` 区分整数和字符串 ID，避免数字 `1` 与字符串 `"1"` 混淆。
- postings 中保存可检索词的 `tf` 与位置列表；短语查询依赖位置列表。
- `stop_positions` 保存停止词位置，不参与 df/tfidf，只用于包含停止词的精确短语。
- 保存采用临时文件加原子替换，避免写到一半产生损坏索引。
- 文件目录型文档记录源路径和 mtime；普通 API 文档可没有这些字段。

## 模块组织

```text
kbsearch/
├── errors.py        # SearchError
├── tokenizer.py     # 中英文切词、规范化、停止词、字符 span
├── stemmer.py       # 简化英文词干化
├── index.py         # 倒排索引、postings、df/tf/位置、删除清理
├── parser.py        # 查询 lexer + 递归下降 parser
├── query.py         # 查询编译、同义词扩展、布尔/短语/前缀求值、打分
├── synonyms.py      # 同义词组存储与配置解析
├── snippet.py       # 命中摘要生成
├── persistence.py   # JSON 原子保存/加载
├── engine.py        # KBSearch 公共 API、目录和单文件更新
└── cli.py           # kbsearch-cli 命令行入口
```

## CLI 参数

```text
--directory DIR     扫描目录下（含子目录）的 .txt 文件
--reindex           全量重建目录中的文档（保留已有索引中的同义词与其他文档）
--update FILE       只重建指定文件的 postings
--synonyms FILE     指定同义词文件
--index PATH        索引路径，默认 .kbsearch/index.json
--query TEXT        执行一次查询并退出
--top-k N           返回条数，默认 10，0 为全部
--interactive       强制进入交互模式
--keep-stopwords    新建索引时保留英文停止词
```

## 运行测试

```bash
python3 -m pytest tests/ -v
```

测试覆盖：

- 中英文混合、大小写、数字、标点、停止词边界
- TF/DF、位置、文档长度、重复添加覆盖、删除清理
- AND/OR/NOT、括号优先级、隐式 AND
- 短语和前缀查询
- 可手算固定语料上的 TF-IDF 顺序
- 中英文同义词扩展与去重计分
- JSON 持久化、重启加载、int/str doc_id
- 增量更新后旧词不残留、新词必命中
- `top_k`、空索引、空查询、无命中、非法查询错误
- 删除后查询无残留
- 1MB 级文档和万级文档语料查询性能
- CLI 建索引、查询和增量更新端到端流程
