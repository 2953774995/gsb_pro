# minisearch

一个从零实现的迷你全文搜索引擎：纯 Python 标准库（被测代码零第三方依赖，
仅测试使用 pytest），在内存中维护倒排索引，支持布尔/短语/前缀查询与
TF-IDF 相关性排序。

## 功能特性

- **文档管理**：`add_document`（同 id 覆盖）/ `remove_document` / `document_count`，
  `doc_id` 支持 `int` 与 `str`
- **中英文混合分词**：英文按字母数字切词 + 小写化 + 精简词干化 + 可配置停止词；
  中文按字索引，任意中文查询词均可命中
- **倒排索引**：`term -> {doc_id: [positions]}`，词频、文档频率 df、文档长度实时维护，
  删除文档后无任何残留
- **查询语言**：`AND` / `OR` / `NOT`（一元）+ 括号分组、短语查询 `"exact phrase"`、
  前缀查询 `term*`；非法查询抛出带原因的 `SearchError`
- **相关性排序**：TF-IDF（对数 tf + 平滑 idf），布尔查询结果同样按分数降序；
  `top_k` 截断（`0` 返回全部）；可选 ~80 字符命中摘要
- **命令行工具**：`minisearch-cli` 批量索引目录下 `.txt` 文件并交互式查询

## 项目结构

```
minisearch/
├── __init__.py        # 包入口，导出 SearchEngine / SearchResult / SearchError
├── errors.py          # SearchError 异常
├── stopwords.py       # 内置英文停止词表
├── stemmer.py         # 精简版 Porter 词干化
├── tokenizer.py       # 中英文分词与规范化（输出 (term, position)）
├── index.py           # 倒排索引 InvertedIndex（postings / df / doc length）
├── query.py           # 查询词法分析 + 递归下降解析器 + AST
├── scorer.py          # TF-IDF 打分公式
├── snippet.py         # 命中摘要生成（80 字符窗口）
├── engine.py          # SearchEngine 门面：文档管理 + 查询求值 + 排序
├── cli.py             # minisearch-cli 命令行工具
└── __main__.py        # python -m minisearch 入口
tests/                 # pytest 测试套件（80 个用例）
```

### 架构设计

```
                ┌────────────┐   tokens    ┌───────────────┐
 add_document ─▶│ tokenizer  │────────────▶│ InvertedIndex │
                │ (+stemmer, │             │ term ->       │
                │  stopwords)│             │  {doc: [pos]} │
                └────────────┘             └───────┬───────┘
                                                   │ postings
 query ─▶ query.py (lexer/parser) ─▶ AST ─▶ engine._eval ─▶ {doc: score}
                                                   │            │
                                            scorer.tf_idf       ▼
                                            snippet.make_snippet  排序+top_k
                                                                     │
                                                              SearchResult[]
```

- **分词器**：英文/数字连续段为一个 token（小写化、停止词过滤、词干化）；
  每个 CJK 汉字为独立 token。位置号按原始 token 流计数（停止词也占位置），
  保证短语查询的相邻性判断正确。
- **倒排索引**：`term -> {doc_id: [positions]}`，`tf = len(positions)`，
  `df = len(postings[term])`，二者天然不会失步；另维护
  `doc_id -> 有效词数` 与 `doc_id -> term 集合`，删除文档时按 term 集合
  精确清理全部 postings，空 term 从词典中移除，不留中间态。
- **查询求值**：AST 递归求值为 `{doc_id: score}` 字典——AND 取交集、
  OR 取并集（分数相加）、NOT 取全集补集；短语用位置列表验证相邻；
  前缀遍历词典匹配。最终按 `(-score, doc_id)` 排序。

### 词干化规则（精简 Porter）

按顺序应用以下规则（详见 `stemmer.py`）：

1. 复数：`sses→ss`、`ies→i`、长度 > 3 的词去掉词尾 `s`（`ss` 保留）
2. 去 `-ed` / `-ing`（剩余词干 ≥ 3 字符），随后折叠双写辅音
   （`running → runn → run`）
3. 长度 > 4 的词去 `-ly`

示例：`running→run`、`cats→cat`、`studies→studi`、`caresses→caress`、
`happily→happi`。这是 Porter 算法的确定性简化版本，覆盖最常见英文变形。

### 打分公式

```
tf_weight = 1 + log(tf)        # 对数归一化词频
idf       = log(1 + N / df)    # 平滑逆文档频率（N 为文档总数）
score     = Σ tf_weight * idf  # 对查询中每个命中词求和
```

## 查询语法

| 语法 | 示例 | 说明 |
| --- | --- | --- |
| 单词 | `python` | 自动小写化 + 词干化；中文词按字 AND |
| AND | `python AND web` | 交集，优先级高于 OR |
| OR | `web OR server` | 并集 |
| NOT | `web AND NOT java` | 一元运算符，优先级最高 |
| 括号 | `python AND (web OR server)` | 分组改变优先级 |
| 短语 | `"exact phrase"` | 按位置列表验证相邻出现 |
| 前缀 | `prog*` | 匹配词典中所有以 `prog` 开头的词 |

- `AND` / `OR` / `NOT` 大小写不敏感；优先级 `NOT > AND > OR`，同级左结合。
- 相邻操作数之间省略运算符时按隐式 AND 处理（`a b` 等价于 `a AND b`）。
- 空查询、孤立/悬空的 `AND`/`OR`/`NOT`、括号或引号不配对、裸 `*` 等
  均抛出 `SearchError` 并携带原因。
- 停止词在索引与查询两侧同样被移除（可用
  `SearchEngine(use_stopwords=False)` 或 `SearchEngine(stopwords={...})` 配置）。

## 快速开始

### 作为库使用

```python
from minisearch import SearchEngine, SearchError

engine = SearchEngine()
engine.add_document(1, "Python web server framework")
engine.add_document(2, "Python data science")
engine.add_document("doc-3", "搜索引擎 全文检索")

for hit in engine.search('python AND (web OR server)', top_k=10, with_snippet=True):
    print(hit.doc_id, round(hit.score, 4), hit.snippet)

print(engine.search("搜索引擎")[0].doc_id)   # -> doc-3
engine.remove_document(1)                     # 索引同步清理，无残留
```

### 命令行工具

```bash
# 方式一：免安装，直接运行
python3 -m minisearch <文档目录>

# 方式二：安装后使用 minisearch-cli 命令
pip install .
minisearch-cli <文档目录> --top-k 5
```

CLI 会递归扫描目录下的 `.txt` 文件（相对路径作为 doc_id，首行作为标题），
然后进入交互式查询循环：

```
Indexed 3 document(s) from docs
Query syntax: term  "exact phrase"  prefix*  AND/OR/NOT  (parentheses)
Type :q or :quit to quit.
minisearch> python AND (web OR server) NOT java
 1. python.txt  score=1.8601  Python Web Notes
    Python Web Notes python web server framework
minisearch> :quit
```

输入 `:q` / `:quit` 退出；非法查询会提示原因并继续循环。

## 运行测试

```bash
python3 -m pytest tests/ -v
```

测试覆盖：分词边界（中英文混合/大小写/标点）、索引正确性
（tf/df/覆盖/删除清理）、布尔语义与优先级、短语与前缀查询、
可手算语料的 TF-IDF 排序断言、`top_k` 截断、空索引/空查询/无命中、
非法查询报错、删除无残留、1MB 大文档与 2000 文档的性能冒烟、
CLI 建索引与交互循环。

## 已知限制

- 索引全量驻留内存，未做持久化与增量合并段。
- 中文按字索引（无词典分词），长中文查询等价于逐字 AND。
- 词干化为精简规则，不等同完整 Porter 算法。
- 停止词被移除后仍占位置，因此跨越停止词的短语（如 `"exact the phrase"`
  查询 `"exact phrase"`）不会命中——与 Lucene 的 position increment 行为一致。
