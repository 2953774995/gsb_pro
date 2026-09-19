# minisearch

一个从零实现的迷你全文搜索引擎：内存倒排索引 + TF-IDF 相关性排序，
仅依赖 Python 标准库（测试框架 pytest 除外）。

## 功能概览

- 文档管理：`add_document` / `remove_document` / `document_count`，
  `doc_id` 支持 `int` 与 `str`，同 id 重复添加会覆盖旧文档
- 中英文混合分词：英文按字母数字切词并小写化 + 精简词干化；
  中文按字索引，任意中文查询词均可命中
- 倒排索引：`term -> {doc_id: [positions]}`，维护 df 与文档长度，
  删除文档时同步清理全部 postings，无残留
- 查询语言：`AND` / `OR` / `NOT`、括号分组、`"短语"`（按位置验证相邻）、
  `前缀*`；非法查询抛出带原因的 `SearchError`
- 排序：TF-IDF（`tf` 对数归一化 + `idf = log(1 + N/df)` 平滑），
  布尔查询结果同样按分数降序；`top_k` 截断（默认 10，`0` 返回全部）
- 摘要：可选生成命中词前后共 80 字符的摘要
- CLI：`minisearch-cli` 批量索引目录下 `.txt` 文件并交互式查询

## 目录结构

```
minisearch/
  __init__.py     # 包导出：SearchEngine, SearchError
  errors.py       # SearchError 异常
  tokenizer.py    # 分词、小写化、停止词过滤、精简词干化
  index.py        # 倒排索引（postings / df / doc length / 原文）
  query.py        # 查询词法分析 + 递归下降解析（AST）
  scorer.py       # TF-IDF 打分
  snippet.py      # 命中摘要生成
  engine.py       # SearchEngine 门面：文档管理 + AST 求值 + 排序
  cli.py          # 命令行工具
minisearch-cli    # 可执行入口脚本
tests/            # pytest 测试套件
```

## 架构设计

```
        add_document(doc_id, text)                search(query)
                │                                      │
                ▼                                      ▼
        ┌───────────────┐                    ┌───────────────┐
        │   Tokenizer   │                    │  query.parse  │  词法分析 + 递归下降
        └───────┬───────┘                    └───────┬───────┘
                │ tokens                             │ AST
                ▼                                    ▼
        ┌───────────────┐   term/df/doclen   ┌───────────────┐
        │ InvertedIndex │ ◄───────────────── │ engine._eval  │  集合交并补 + 打分
        └───────────────┘                    └───────┬───────┘
                                                     │ {doc_id: score}
                                                     ▼
                                          按分数降序 + top_k + snippet
```

- **Tokenizer**：英文用正则切出 `[a-z0-9]+` 并小写化；每个 CJK 汉字
  是独立 token。停止词在分词阶段过滤，位置在过滤后连续编号，
  因此短语匹配不受停止词影响（"state of the art" 可匹配 "state art"）。
- **InvertedIndex**：`term -> {doc_id: [position, ...]}`，词频即位置
  列表长度；另维护 `doc_lengths`、原文（供摘要）与每文档词项集合，
  删除文档时按词项集合精确清理 postings，空词项一并移除。
- **查询解析**：优先级 `NOT > AND > OR`，括号可覆盖；短语按位置列表
  验证相邻出现；前缀查询遍历词典匹配后按 OR 合并。
- **打分**：`score = (1 + log(tf)) * log(1 + N/df)`；AND 取交集、
  OR 取并集，分数相加；NOT 取补集且贡献 0 分（只过滤不改排序）。

## 规范化与词干化规则

- 英文 token 全部小写化；可配置停止词表（默认含 a/the/is/of 等常用词，
  `SearchEngine(use_stopwords=False)` 可关闭，也可传入自定义词表）。
- 精简 Porter 词干化（按顺序取第一条命中的规则）：
  1. `ies` → `y`（studies → study）
  2. 去掉 `ing` / `ed`（剩余词干 ≥ 3 字符且含元音；结尾双辅音合并，
     running → run、played → play）
  3. 去掉结尾 `s`（结尾为 ss/us/is 时保留；s/x/z + es 结尾去掉两个字母，
     cats → cat、foxes → fox、class → class）
  4. 长度 ≤ 2 的词保持不变

## 查询语法

| 语法 | 示例 | 说明 |
| --- | --- | --- |
| 单词 | `python` | 大小写不敏感，查询词同样词干化 |
| AND / OR | `python AND web` | 二元运算符，可链式 |
| NOT | `server AND NOT java` | 一元，作用于子表达式 |
| 括号 | `python AND (web OR server)` | 改变优先级 |
| 短语 | `"quick brown fox"` | 按位置验证相邻出现 |
| 前缀 | `serv*` | 匹配词典中所有该前缀词项 |

空查询、孤立的 `AND`/`OR`、括号不配对、未闭合引号、空短语、
非法 `*` 位置等均抛出 `SearchError` 并附带原因。

## 快速开始

```python
from minisearch import SearchEngine

engine = SearchEngine()
engine.add_document(1, "Python is great for web servers")
engine.add_document(2, "全文搜索引擎的实现")
engine.add_document("doc-3", "Java powers enterprise servers")

for hit in engine.search('python AND NOT java', top_k=10, with_snippet=True):
    print(hit["doc_id"], round(hit["score"], 4), hit.get("snippet", ""))

engine.remove_document(1)   # 索引与查询结果同步更新，无残留
```

## 命令行工具

```bash
./minisearch-cli /path/to/docs          # 索引目录下全部 .txt 文件
python3 -m minisearch.cli /path/to/docs # 等价写法
./minisearch-cli docs --top-k 5 --no-stopwords
```

进入交互界面后直接输入查询（首行作为标题展示，结果含 doc_id/分数/摘要）：

```
minisearch> python AND (web OR server)
minisearch> "exact phrase"
minisearch> 搜索引擎
minisearch> :remove python.txt
minisearch> :count
minisearch> :quit
```

## 运行测试

```bash
python3 -m pytest tests/ -v
```

测试覆盖：分词边界（中英文混合/大小写/标点）、索引正确性
（词频/df/覆盖添加/删除清理）、布尔语义与优先级、短语与前缀查询、
可手算的 TF-IDF 排序、top_k 截断、空索引/空查询/无命中、非法查询报错、
删除后无残留，以及 1MB 级大文档的构建与查询性能。
