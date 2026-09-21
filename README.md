# kbsearch

售后知识库离线检索工具。面向上门维修现场无网环境，在笔记本上离线检索维修手册与
历史工单（一批 `.txt` 文件）。**仅使用 Python 标准库**（测试框架 pytest 除外），
Python 3.7+ 即可运行。

## 功能概览

- 文档管理：`add_document` / `remove_document` / `document_count`，`doc_id` 支持
  `int` 与 `str`，重复添加同一 `doc_id` 会覆盖旧文档
- 中英文混合分词：英文按字母数字切词 + 小写化 + 简化词干化；中文按字索引（unigram）
- 倒排索引：`term -> postings`（词频 tf + 位置列表），维护 df 与每篇文档长度，
  删除文档时同步清理全部 postings，无残留
- 查询语言：布尔 `AND/OR/NOT` + 括号、短语 `"exact phrase"`、前缀 `term*`、
  相邻词隐含 AND；非法查询抛 `SearchError`（带原因）
- TF-IDF 打分排序（对数 tf、平滑 idf），布尔结果同样按分数降序；`top_k` 截断
- 同义词扩展：可配置同义词文件，中英文均可，扩展词与原词融合打分不重复计数
- 索引持久化：JSON 格式落盘，重启后直接加载查询；支持单文件增量更新
- 命中摘要：命中词前后共截取约 80 字符
- 命令行工具 `kbsearch-cli`：批量建索引、交互式查询、`--reindex` 全量重建、
  `--update <file>` 增量更新

## 架构设计

```
kbsearch/
├── tokenizer.py   # 分词、小写化、词干化、停止词过滤（含位置偏移）
├── index.py       # 倒排索引：postings / doc_lengths / doc_texts / doc_meta
├── query.py       # 查询词法分析、递归下降解析（AST）、AST 求值器
├── synonyms.py    # 同义词表（文件加载、查询词扩展）
├── scorer 逻辑     # 内置于 query.Evaluator：TF-IDF（对数 tf + 平滑 idf）
├── snippet.py     # 命中摘要生成
├── storage.py     # JSON 持久化（doc_id 类型保持 int/str）
├── core.py        # KBSearch 门面类：文档管理 / search / save / load
└── cli.py         # 命令行与交互式 REPL
```

数据流：`add_document` → Tokenizer 分词 → InvertedIndex 记录
`term -> {doc_id: [tf, [positions]]}`；`search` → 解析查询为 AST →
Evaluator 对 AST 自底向上求值，每个节点产生 `{doc_id: score}` 映射 →
合并排序 → 可选摘要。

### 分词与规范化规则

- 英文/数字：`[a-zA-Z0-9]+` 切词并小写化；大小写不敏感
- 简化词干化（`tokenizer.stem`，按序至多命中一条）：
  1. 长度 > 4 且以 `ing` 结尾 → 去掉 `ing`（repairing → repair）
  2. 长度 > 3 且以 `ed` 结尾 → 去掉 `ed`（repaired → repair）
  3. 长度 > 3 且以 `ly` 结尾 → 去掉 `ly`（quickly → quick）
  4. 复数规则（Porter step 1a 简化版）：`sses→ss`、`ies→i`、`ss` 不变，
     其余长度 > 2 的尾 `s` 去掉（repairs → repair，noises → noise，class → class）
- 停止词：内置常用英文停止词表（a/the/is/of/and/or/not 等），
  `KBSearch(use_stopwords=False)` 可关闭
- 中文：每个汉字单独成为一个 token（按字索引）。多字中文查询词按
  “连续 token 序列”精确匹配，因此任意中文查询词都能命中且不会误配

### 查询语法

| 语法 | 示例 | 说明 |
| --- | --- | --- |
| 单词 | `压缩机` / `compressor` | 多字中文词按连续序列匹配；英文自动词干化 |
| AND | `压缩机 AND 异响` | 交集 |
| OR | `异响 OR 不制冷` | 并集 |
| NOT | `压缩机 AND NOT 空调` | 一元运算符，作用于子表达式 |
| 括号 | `压缩机 AND (异响 OR 不制冷)` | 优先级 `NOT` > `AND` > `OR` |
| 隐含 AND | `压缩机 异响` | 相邻词元等价于 AND |
| 短语 | `"quick brown fox"` | 按位置列表验证相邻出现 |
| 前缀 | `comp*` | 遍历词典匹配前缀（匹配的是词干化后的索引词） |

只有大写 `AND/OR/NOT` 是运算符；小写是普通词（通常为停止词被过滤）。
非法查询（空查询、孤立的 `AND/OR`、括号不配对、引号未闭合、空前缀 `*`、
纯停止词等）抛出 `SearchError` 并附带原因。

### 打分与排序

- `tf_weight = 1 + log(tf)`，`idf = log(1 + N / df)`，词项得分 = 两者乘积
- 布尔结果：AND 取交集、OR 取并集，文档得分为各子表达式得分之和，按分数降序
- 同义词/前缀命中的多个变体合并为一个“词项组”：组内 tf 相加、df 取并集，
  因此扩展词与原词不会重复计数
- `top_k` 默认 10，`0` 表示返回全部；分数相同按 `str(doc_id)` 稳定排序

### 同义词文件

每行一组，用 `=`（或 `,`、`，`）分隔，`#` 开头为注释：

```
冰箱=冰柜=冷藏柜
维修=修理
fridge=refrigerator
```

仅对查询中的“裸词”扩展（短语与前缀查询不扩展）。扩展在分词前进行，
因此多字中文词（如 `冷藏柜`）也能正确扩展。

### 索引文件格式

JSON（UTF-8），顶层字段：

```json
{
  "version": 1,
  "use_stopwords": true,
  "doc_lengths": {"i:42": 10, "s:manual-a": 25},
  "doc_texts":   {"i:42": "原文...", "...": "..."},
  "doc_meta":    {"i:42": {"source": "/abs/path.txt", "title": "首行标题", "mtime": 0.0}},
  "postings":    {"压缩机词元": {"i:42": [tf, [pos1, pos2]]}}
}
```

- `doc_id` 键带类型前缀：`i:` 为 int，`s:` 为 str，加载后类型不变
- `doc_texts` 使索引自包含：重启加载后无需重扫原文即可查询并生成摘要
- `df` 由 postings 派生，不单独存储

## 使用方式

### Python API

```python
from kbsearch import KBSearch, SynonymMap

kb = KBSearch(synonyms=SynonymMap.from_file("synonyms.txt"))
kb.add_document(1, "冰箱压缩机异响，维修手册：更换压缩机。")
kb.add_document("ticket-2", "空调不制冷，冷媒泄漏。")

for hit in kb.search('压缩机 AND (异响 OR 不制冷)', top_k=10, with_snippet=True):
    print(hit["doc_id"], round(hit["score"], 4), hit.get("snippet", ""))

kb.save("kbsearch.index.json")          # 持久化
kb2 = KBSearch.load("kbsearch.index.json")  # 重启后直接加载查询
kb2.remove_document(1)                  # 删除文档，postings 同步清理
```

### 命令行

```bash
# 从目录批量建索引（扫描 .txt，首行作标题），随后进入交互式查询
./kbsearch-cli --dir ./docs --index kb.json --synonyms syn.txt

# 全量重建
./kbsearch-cli --dir ./docs --index kb.json --reindex

# 单文件增量更新（只重建该文档的 postings）
./kbsearch-cli --index kb.json --update ./docs/工单0001.txt

# 重启后直接加载索引查询（不重扫文档）
./kbsearch-cli --index kb.json
```

也可以用 `python3 -m kbsearch ...` 调用相同功能。交互界面中输入查询回车，
展示 `doc_id`、分数与命中摘要；输入 `quit` 退出。不带 `--reindex` 重复执行
`--dir` 时按文件 mtime 跳过未变化文档。

## 测试

```bash
python3 -m pytest tests/ -v
```

测试覆盖：分词边界（中英混合/大小写/标点/词干/停止词）、索引正确性
（tf/df/位置/覆盖添加/删除清理）、布尔语义与优先级、短语与前缀、
TF-IDF 可手算排序、同义词扩展与防重复计数、持久化与重启加载、
增量更新一致性、top_k 截断、空索引/空查询/无命中、非法查询报错、
删除无残留、1MB 大文档与一万篇文档语料的性能回归。
