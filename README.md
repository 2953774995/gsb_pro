# minisearch

纯 Python 标准库实现的迷你全文搜索引擎：内存倒排索引 + 布尔/短语/前缀查询 + TF-IDF 相关性排序。无任何第三方依赖（测试框架 pytest 除外）。

## 功能特性

- **文档管理**：`add_document`（同 doc_id 覆盖）/ `remove_document`（同步清理索引）/ `document_count`，doc_id 支持 int 与 str
- **中英文混合分词**：英文按字母数字切词并小写化 + 简化词干化；中文按字索引，任意中文查询词可命中
- **倒排索引**：term -> postings（词频 tf + 位置列表），维护 df 与每篇文档有效词数
- **查询语言**：`AND` / `OR` / `NOT`（一元）/ 括号分组 / `"短语"` / `前缀*`，相邻词项隐含 AND
- **TF-IDF 排序**：tf 对数归一化 `(1 + log10(tf))`，idf 平滑 `log(1 + N/df)`，布尔查询同样按分数降序
- **结果**：`top_k` 截断（默认 10，0 返回全部），可选 80 字符命中摘要
- **CLI**：`minisearch-cli` 从目录批量索引 .txt 并交互式查询

## 快速开始

```python
from minisearch import SearchEngine

engine = SearchEngine()
engine.add_document(1, "Python is great for web server programming")
engine.add_document("doc2", "我爱北京天安门")
engine.add_document("doc3", "Java server programming")

results = engine.search("python AND NOT java", with_snippet=True)
for r in results:
    print(r["doc_id"], r["score"], r.get("snippet"))

engine.remove_document("doc3")   # 索引同步清理，无残留
print(engine.document_count())   # 2
```

## 查询语法

| 语法 | 示例 | 说明 |
| --- | --- | --- |
| 词项 | `python` | 大小写不敏感，自动词干化；中文词按字隐含 AND |
| AND | `python AND web` | 交集，分数相加 |
| OR | `python OR java` | 并集，分数相加 |
| NOT | `python AND NOT java` | 一元运算符，作用于子表达式（补集） |
| 括号 | `python AND (web OR server)` | 分组，AND 优先级高于 OR |
| 短语 | `"quick brown fox"` | 按位置列表验证相邻出现 |
| 前缀 | `prog*` | 遍历词典匹配前缀，命中项分数求和 |
| 隐含 AND | `python web` | 相邻词项等价于 AND |

非法查询（空查询、孤立的 `AND`/`OR`、括号不匹配、未闭合引号、非法通配符等）抛出 `SearchError` 并带原因。

## 分词与规范化

- **英文**：正则 `[A-Za-z0-9]+` 切词，小写化。
- **词干化**（简化 Porter，可用 `SearchEngine(use_stemming=False)` 关闭）：
  1. 复数：`sses->ss`（caresses->caress）、`ies->i`（ponies->poni）、保留 `ss`、其余去词尾 `s`（cats->cat）；
  2. 后缀：去 `ing`/`ed`（剩余词干长度 >= 3），结尾双写辅音再去一个（stopped->stop、running->run）。
- **停止词**：内置常用英文停止词表（a/the/is/of/and/or 等），可用 `SearchEngine(use_stopwords=False)` 或 `stopwords={...}` 自定义。停止词不占索引但保留位置编号。
- **中文**：CJK 汉字按字符单位切分（按字索引），因此任意中文查询词都能命中；中文查询词按隐含 AND 组合，短语查询 `"北京天"` 可验证相邻。

## 架构设计

```
minisearch/
├── tokenizer.py   # 分词、小写化、简化 Porter 词干化、停止词表
├── index.py       # InvertedIndex：postings / df / doc_length，增删文档
├── query.py       # 查询词法分析、递归下降解析（AST）、求值与 TF-IDF 打分
├── engine.py      # SearchEngine：文档管理 + search() 入口
├── snippet.py     # 命中摘要（命中词前后共 80 字符窗口）
├── cli.py         # 命令行：目录批量建索引 + 交互式查询
└── errors.py      # SearchError
```

- **索引**：`term -> {doc_id: {tf, positions}}`；`df = len(postings[term])`；删除文档时按 `doc_terms` 精确清理该文档全部 postings，空 term 从词典移除，不留中间态。
- **打分**：`score(term, doc) = (1 + log10(tf)) * log(1 + N/df)`；AND 取交集、OR 取并集，分数均为子表达式求和；NOT 返回补集（得分 0）。
- **排序**：分数降序，同分按 doc_id 字符串排序保证确定性；`top_k=0` 返回全部。

## 命令行工具

```bash
./minisearch-cli /path/to/docs        # 或 python3 -m minisearch /path/to/docs
```

扫描目录下全部 `.txt` 文件（doc_id 为文件名，标题取首个非空行），进入交互式查询：

```
minisearch> python AND (web OR server) AND NOT java
minisearch> "exact phrase"
minisearch> prog*
minisearch> :remove doc1     # 删除文档
minisearch> :count           # 文档数
minisearch> :quit            # 退出
```

## 运行测试

```bash
python3 -m pytest tests/ -v
```

测试覆盖：分词边界（中英文混合/大小写/标点/停止词/词干化）、索引正确性（tf/df/覆盖/删除清理）、布尔语义与优先级、短语与前缀、可手算的 TF-IDF 排序、top_k 截断、空索引/空查询/无命中、非法查询报错、删除无残留、1MB 大文档性能、CLI 建索引与交互。
