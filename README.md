# sqlq — 迷你内存 SQL 关系型查询引擎

`sqlq` 是一个从零实现的迷你 SQL 引擎：自带词法分析器、递归下降语法分析器、
表达式求值器与查询执行器，所有表数据保存在内存中。**仅依赖 Python 标准库**
（测试仅使用 `pytest`），代码中不出现 `sqlite3`、`pandas` 等第三方依赖。

## 快速开始

要求 Python 3.8+，无需安装依赖。

```bash
# 1) 直接跑测试
python3 -m pytest tests/ -v

# 2) 交互式 REPL（三种等价方式）
python3 -m sqlq
./bin/sqlq-cli

# 3) 执行 SQL 脚本文件
python3 -m sqlq examples/demo.sql
./bin/sqlq-cli examples/demo.sql

# 4) 通过管道批量执行
cat examples/demo.sql | python3 -m sqlq
```

可选安装（提供全局 `sqlq-cli` 命令）：

```bash
pip install -e .
sqlq-cli examples/demo.sql
```

### REPL 用法

```text
sqlq> CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, score REAL);
sqlq> INSERT INTO users VALUES (1, 'ann', 9.5);
sqlq> SELECT * FROM users;
...
sqlq> SELECT name, COUNT(*) FROM users GROUP BY name ORDER BY 2 DESC;
```

- 语句以分号 `;` 结束，分号前可以跨行，出现续行提示 `...>`。
- 元命令：`.tables`（列表）、`.schema [TABLE]`（建表语句）、`.help`、`.exit`。
- 单条非法语句只打印 `Error: ...`，不会退出会话。

## Python API

```python
from sqlq import Engine, SqlqError

engine = Engine()

# execute() 执行单条语句（必须恰好一条，且以分号结尾）
result = engine.execute("SELECT name, score FROM users WHERE score > 5;")
print(result.columns)   # ['name', 'score']
print(result.rows)      # [('ann', 9.5), ...]
print(result.tag)       # '2 row(s)'

# execute_script() 一次执行多条语句，返回结果列表
engine.execute_script("""
    CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);
    INSERT INTO t VALUES (1, 'a');
    INSERT INTO t VALUES (2, 'b');
""")

# 一切错误都抛 SqlqError（带行列号）
try:
    engine.execute("SELECT nope FROM t;")
except SqlqError as err:
    print(err, err.line, err.column)
```

`QueryResult` 字段：

| 字段 | 含义 |
| --- | --- |
| `columns` | 输出列名列表（`SELECT` 以外为空） |
| `rows` | 行数据列表，每行为 tuple |
| `statement` | 语句类型（`SELECT` / `INSERT` / ...） |
| `rowcount` | DML 影响行数（`SELECT` 为 -1） |
| `tag` | 形如 `3 row(s)` / `2 row(s) updated` 的状态摘要 |

## 支持的语法清单

### 通用规则

- 每条语句以 `;` 结尾；关键字大小写不敏感（`select` 等同 `SELECT`）。
- 标识符（表名/列名/别名）为字母/下划线开头的字母数字串，按名称大小写不敏感
  解析，输出表头保留建表/别名时的原始拼写。
- 字面量：
  - 整数 `42`、浮点 `3.14`、科学计数 `1e3` / `2.5E-2`
  - 字符串使用单引号，内部单引号用 `''` 转义：`'it''s ok'`
  - `NULL`
- 注释：行注释 `-- ...`，块注释 `/* ... */`（支持嵌套）。

### DDL

```sql
CREATE TABLE products (
    id       INTEGER PRIMARY KEY,
    name     TEXT,
    price    REAL,
    stock    INTEGER
);
DROP TABLE products;
```

- 列类型：`INTEGER`（`INT` 为别名）、`REAL`、`TEXT`。
- 每列只能内联声明 `PRIMARY KEY`；主键列不允许重复值、不允许 NULL。
- 重复建表、删除不存在的表均抛 `SqlqError`。

### DML

```sql
INSERT INTO products VALUES (1, 'book', 12.5, 10);
INSERT INTO products (id, name) VALUES (2, 'pen');        -- 其余列为 NULL
UPDATE products SET price = price * 0.9 WHERE name = 'book';
UPDATE products SET stock = 0;                            -- 不带 WHERE 作用全表
DELETE FROM products WHERE stock = 0;
DELETE FROM products;                                     -- 清空全表
```

- 插入/更新值按列类型强校验：`INTEGER` 只接受整型，`REAL` 接受整型或浮点
  （整型会提升为浮点），`TEXT` 只接受字符串；不匹配抛类型错误。
- 更新主键导致与其他行冲突时抛主键冲突错误。

### SELECT

```sql
SELECT [DISTINCT] { * | expr [AS alias], ... }
[FROM table]
[WHERE expr]
[GROUP BY expr, ...]
[HAVING expr]
[ORDER BY expr [ASC|DESC], ...]
[LIMIT n]
[OFFSET m]                      -- 也支持 LIMIT m, n 写法
```

- **投影**：指定列、表达式、`*` 通配、列别名 `AS`；表达式默认列名由表达式
  渲染得到（如 `SUM(price)`、`1 + 2`）。
- **WHERE**：
  - 比较 `= == != <> < <= > >=`（`==` 等价于 `=`，`<>` 等价于 `!=`）
  - 逻辑 `AND OR NOT`、括号分组
  - 算术 `+ - * /`（除法始终为浮点；除以 0 报错；一元正负号）
  - `x IS NULL` / `x IS NOT NULL`
  - 字符串按字典序比较；数字与字符串互相比较报类型错误
- **聚合**：`COUNT(*)`、`COUNT(expr)`、`SUM`、`AVG`、`MIN`、`MAX`，
  支持 `COUNT(DISTINCT x)`、`SUM(DISTINCT x)` 等；`SUM/AVG` 作用于 TEXT 列报错。
- **GROUP BY / HAVING**：支持按列或任意表达式分组；`HAVING` 必须配合
  GROUP BY 或聚合；投影中出现的裸列必须是分组列或被聚合包裹。
- **ORDER BY**：多列、`ASC`/`DESC`、输出别名、输出列序号（`ORDER BY 2`）
  以及不在投影中的表达式。NULL 排序采用 SQLite/MySQL 惯例：ASC 时 NULL 在前、
  DESC 时 NULL 在后。
- **LIMIT / OFFSET**：非负整数字面量；支持 `LIMIT a, b` 等价 `LIMIT b OFFSET a`。
- **DISTINCT**：对整行去重，NULL 彼此视为相同。
- 不带 FROM 的 `SELECT` 支持常量表达式（`SELECT 1 + 1;`），但不能引用列或聚合。

### NULL 三值逻辑

- 任何与 NULL 的算术/比较结果都是 NULL（未知），WHERE 只接受明确为真的行。
- `NULL AND FALSE = FALSE`、`TRUE OR NULL = TRUE`、`NOT NULL = NULL`。
- 聚合忽略 NULL：`COUNT(expr)` 不计 NULL，`SUM/AVG` 跳过 NULL；
  空表或全 NULL 组时 `COUNT` 为 0，其余聚合返回 NULL。
- GROUP BY 将所有 NULL 归为同一组。

## 架构设计

```
sqlq/
├── errors.py      # SqlqError：携带行列号的统一异常
├── lexer.py       # 词法分析器：文本 -> Token 流
├── ast_nodes.py   # AST 节点（表达式 / 语句，dataclass）
├── parser.py      # 递归下降 Parser：Token -> AST（运算符优先级分层）
├── evaluator.py   # 表达式求值：三值逻辑、类型检查、默认列名渲染
├── executor.py    # 存储结构 + Engine：DDL/DML 执行与 SELECT 流水线
├── cli.py         # REPL / 脚本执行 / 对齐表格渲染（含 CJK 宽度）
└── __main__.py    # python3 -m sqlq 入口
bin/sqlq-cli       # 免安装启动脚本
tests/             # 136 个 pytest 用例
examples/demo.sql  # 建表/插入/聚合/排序/更新/删除完整演示
```

### SELECT 执行流水线

`executor.Engine._select` 按经典关系代数顺序处理：

1. 语义校验：列/表是否存在、聚合是否出现在合法子句、SUM/AVG 类型、
   分组作用域（裸列必须分组或被聚合）。
2. `WHERE` 过滤（三值逻辑，只有真才保留）。
3. 分组：有 GROUP BY 时按表达式值哈希分桶（NULL 同组，保持首次出现顺序）；
   无 GROUP BY 但存在聚合时视为“整个结果集一个组”，空表也产生一个聚合行。
4. 计算所有聚合表达式并缓存，供投影/HAVING/ORDER BY 复用。
5. `HAVING` 过滤分组。
6. 投影：`*` 展开、别名处理、表达式默认列名。
7. `DISTINCT` 整行去重。
8. `ORDER BY` 多键稳定排序（别名 / 列序号 / 表达式，NULL 特殊处理）。
9. `OFFSET` / `LIMIT` 分页。

### 表达式优先级（从低到高）

```
OR < AND < NOT < 比较 (= != < <= > >= / IS [NOT] NULL)
   < 加减 + - < 乘除 * / < 一元 - + NOT < 主表达式 (字面量/列/聚合/括号)
```

不支持链式比较（`a = b = c` 会报语法错误），也不支持 JOIN、嵌套子查询。

## 错误处理示例

所有错误均为 `SqlqError`，语法错误带行列号：

```text
Error: unknown column 'nope'
Error: unknown table 'orders'
Error: SUM cannot be applied to TEXT column 'name'
Error: primary key violation: duplicate value 1 in column 'id'
Error: expected ';' but found end of input (line 1, column 9)
Error: division by zero
```

## 运行测试

```bash
python3 -m pytest tests/ -v
```

测试覆盖：词法/语法错误边界、表达式优先级与 NULL 传播、聚合与
GROUP BY/HAVING（含空表、NULL 组、DISTINCT 聚合、TEXT 聚合报错）、
ORDER BY/LIMIT/OFFSET、DISTINCT、UPDATE/DELETE 语义与行数、主键冲突、
限定列名、SELECT 无 FROM、以及 CLI 的渲染/REPL/文件与管道执行。
