# storelens

连锁便利店运营数据本地分析工具。总部运营分析师在出差笔记本上**离线**分析各门店每日导出的营业数据（商品档案、订单流水、库存快照，JSON 格式）。

- **纯 Python 标准库实现**，被测代码零第三方依赖（仅测试使用 pytest），无需安装数据库软件，符合办公电脑安全策略。
- 自带一套为分析场景设计的、风格接近 SQL 的查询语言，包含自研词法分析器（tokenizer）与递归下降解析器（parser）。
- 数据存放于内存结构，行保持插入顺序。

## 快速开始

```bash
# 运行测试（需要 pytest）
python3 -m pytest tests/ -v

# 交互式命令行
./storelens-cli
# 或
python3 -m storelens

# 批量执行脚本文件
./storelens-cli examples/demo.sql
```

交互式会话示例：

```
storelens> CREATE TABLE orders (order_id INTEGER PRIMARY KEY, store TEXT, amount REAL);
storelens> .import orders examples/orders.json
storelens> SELECT store, COUNT(*) AS n, SUM(amount) AS revenue
       ... FROM orders
       ... WHERE amount IS NOT NULL
       ... GROUP BY store
       ... HAVING SUM(amount) >= 10
       ... ORDER BY revenue DESC
       ... LIMIT 3;
```

`examples/` 目录提供了商品档案、订单流水、库存快照三份示例 JSON 与一条完整操作链路的演示脚本 `demo.sql`。

## 架构设计

```
storelens/
├── errors.py       # StorelensError：所有语法/语义/运行时错误的统一异常
├── lexer.py        # 词法分析器：文本 -> Token 流（关键字大小写不敏感、
│                   #   字符串 '' 转义、整数/浮点字面量、行列号跟踪）
├── ast_nodes.py    # AST 节点定义（表达式与六类语句）
├── parser.py       # 递归下降解析器：Token 流 -> AST（优先级分层：
│                   #   OR < AND < NOT < 比较/IS NULL < 加减 < 乘除模 < 一元 < 原子）
├── types.py        # INTEGER / REAL / TEXT 类型系统与值 coercion 规则
├── table.py        # 内存表：列定义、主键约束、有序行存储
├── expressions.py  # 表达式求值：SQL 三值逻辑（NULL 比较为未知、
│                   #   AND/OR/NOT 真值表、算术 NULL 传播）
├── engine.py       # 执行器：语句分发、SELECT 流水线（WHERE -> 分组聚合 ->
│                   #   HAVING -> DISTINCT -> ORDER BY -> LIMIT/OFFSET）、
│                   #   UPDATE/DELETE、JSON 批量导入
└── cli.py          # 命令行：交互式 REPL、格式化结果表格、批量执行文件
```

数据流：`文本 -> lexer.tokenize -> Parser.parse_script -> AST -> Engine 执行 -> Result（列名 + 行数据）`。

## 查询语言语法清单

每条语句必须以分号 `;` 结尾；关键字大小写不敏感；字符串用单引号，串内单引号写作 `''`；支持 `--` 行注释。

### 数据集管理

```sql
CREATE TABLE orders (order_id INTEGER PRIMARY KEY, store TEXT, amount REAL);
DROP TABLE orders;
```

- 列类型：`INTEGER`、`REAL`、`TEXT`。
- `PRIMARY KEY`：主键列不允许重复值，也不允许 NULL；导入重复单号会报错。

### 数据操作

```sql
INSERT INTO orders (order_id, store, amount) VALUES (1, 'S01', 9.9), (2, 'S02', 5.0);
UPDATE orders SET amount = 10.5, store = 'S03' WHERE order_id = 1;
DELETE FROM orders WHERE amount IS NULL;
DELETE FROM orders;            -- 不带 WHERE 作用于整个数据集
```

### 查询

```sql
SELECT [DISTINCT] expr [AS alias], ... | *
FROM table
[WHERE expr]
[GROUP BY expr, ...]
[HAVING expr]
[ORDER BY expr [ASC | DESC], ...]
[LIMIT n [OFFSET m]];
```

- **表达式**：比较 `= != < <= > >=`（字符串按字典序）、逻辑 `AND OR NOT`（三值逻辑）、算术 `+ - * / %`、括号分组、`IS NULL` / `IS NOT NULL`。
- **聚合函数**：`COUNT(*) / COUNT(col)`、`SUM`、`AVG`、`MIN`、`MAX`，配合 `GROUP BY` 与 `HAVING`。
- **排序分页**：`ORDER BY` 支持多列与 `ASC/DESC`；`LIMIT` 支持 `OFFSET`。
- **DISTINCT**：结果行去重。

### 缺失值（NULL）语义

- 任何与缺失值的比较结果为**未知**，不匹配 `WHERE`（三值逻辑）。
- 聚合忽略缺失值：`COUNT(col)` 不计 NULL，`SUM/AVG/MIN/MAX` 跳过 NULL。
- `GROUP BY` 将所有缺失值归为同一组；排序时 NULL 总是排在最后。

## Python API

```python
from storelens import Engine, StorelensError

engine = Engine()
engine.execute("CREATE TABLE orders (order_id INTEGER PRIMARY KEY, store TEXT, amount REAL);")

# 从 JSON 文件批量导入（JSON 数组，元素为列名 -> 值的对象）
engine.import_json("orders", "examples/orders.json")

result = engine.execute(
    "SELECT store, SUM(amount) AS revenue FROM orders "
    "WHERE amount IS NOT NULL GROUP BY store ORDER BY revenue DESC LIMIT 5;")
print(result.columns)   # ['store', 'revenue']
print(result.rows)      # [('S02', 27.5), ...]

# 一次执行多条语句，返回 Result 列表
results = engine.execute_script("INSERT INTO orders VALUES (1, 'S01', 9.9); SELECT COUNT(*) FROM orders;")
```

所有错误（语法错误、未知数据集/列、类型不匹配、主键冲突、除零等）都抛出带明确信息的 `StorelensError`，语法错误附带行列号。

## 命令行工具 storelens-cli

```bash
./storelens-cli              # 交互式
./storelens-cli script.sql   # 批量执行文件（也可用 -f）
```

交互模式元命令：

| 命令 | 说明 |
| --- | --- |
| `.help` | 显示帮助 |
| `.tables` | 列出所有数据集 |
| `.schema TABLE` | 显示列定义 |
| `.import TABLE FILE` | 从 JSON 文件批量导入 |
| `.read FILE` | 执行文件中的语句 |
| `.exit` / `.quit` | 退出 |

查询结果以等宽对齐表格展示（含表头与行数统计）。批量脚本中可以混写 SQL 语句与 `.import` 等元命令（见 `examples/demo.sql`）。

## 测试

```bash
python3 -m pytest tests/ -v
```

测试覆盖：词法/语法错误边界（缺分号、未知关键字、括号不匹配、未闭合字符串）、表达式求值（优先级、三值逻辑、NULL 传播）、聚合与 GROUP BY/HAVING、ORDER BY/LIMIT/OFFSET、DISTINCT、UPDATE/DELETE 语义、主键约束冲突、JSON 导入（含原子性）、空数据集/空结果集边界、CLI 表格格式化与批量执行。
