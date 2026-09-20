# storelens

连锁便利店运营数据本地分析工具。总部运营分析师在出差笔记本上**离线**分析各门店每日导出的营业数据（商品档案、订单流水、库存快照等 JSON 文件）。

- **纯 Python 标准库实现**，无任何第三方依赖（测试框架 pytest 除外），不需要安装数据库软件
- 自带一套为分析场景设计的类 SQL 查询语言（自研词法分析器 + 递归下降解析器）
- 数据存储在内存结构中，行保持插入顺序
- 提供 Python API（`Engine`）与命令行工具（`storelens-cli`）

要求：Python 3.7+（开发验证环境为 Python 3.9）。

## 快速开始

```bash
# 交互式 shell
./storelens-cli
# 或
python3 -m storelens

# 批量执行脚本文件
./storelens-cli analysis.sql
```

交互式 shell 中每条语句以 `;` 结尾，支持元命令：

```
.help                 显示帮助
.tables               列出所有数据集
.schema NAME          查看数据集结构
.import NAME FILE     将 JSON 文件（对象数组）批量导入数据集 NAME
.quit                 退出
```

完整操作链路示例：

```sql
CREATE TABLE orders (order_id INTEGER PRIMARY KEY, store TEXT,
                     sku INTEGER, qty INTEGER, amount REAL);
```

```
storelens> .import orders /path/to/orders.json
storelens> SELECT store, COUNT(*) AS n, SUM(amount) AS revenue
   ...> FROM orders
   ...> WHERE amount IS NOT NULL
   ...> GROUP BY store
   ...> HAVING SUM(amount) > 100
   ...> ORDER BY revenue DESC
   ...> LIMIT 10 OFFSET 0;
storelens> UPDATE orders SET qty = 0 WHERE order_id = 42;   -- 修正脏数据
storelens> DELETE FROM orders WHERE store = 'CLOSED';
```

### JSON 导入格式

文件内容为一个 JSON 数组，每个元素是一个对象（键 = 列名）：

```json
[
  {"order_id": 1, "store": "S01", "sku": 101, "qty": 2, "amount": 7.0},
  {"order_id": 2, "store": "S02", "sku": 103, "qty": null, "amount": null}
]
```

缺失的键按 NULL 处理；未知键、类型不匹配、主键重复都会抛出带行号的 `StorelensError`。

### Python API

```python
from storelens import Engine, StorelensError

engine = Engine()
engine.execute("CREATE TABLE orders (order_id INTEGER PRIMARY KEY, store TEXT, amount REAL);")
engine.import_json("orders", "orders.json")          # 批量导入，返回行数

result = engine.execute("SELECT store, SUM(amount) AS total FROM orders GROUP BY store;")
print(result.columns)   # ['store', 'total']
print(result.rows)      # [('S01', 7.0), ...]

results = engine.execute_script("DELETE FROM orders WHERE amount IS NULL; SELECT COUNT(*) AS n FROM orders;")
```

## 支持的语法清单

关键字**大小写不敏感**；每条语句必须以 `;` 结尾；字符串用单引号，串内单引号写两个（`'it''s'`）；支持 `--` 行注释。

| 类别 | 语法 |
| --- | --- |
| 建数据集 | `CREATE TABLE name (col TYPE [PRIMARY KEY], ...)`，`TYPE ∈ {INTEGER, REAL, TEXT}` |
| 删数据集 | `DROP TABLE name` |
| 插入 | `INSERT INTO name [(col, ...)] VALUES (...), (...)` |
| 更新 | `UPDATE name SET col = expr [, ...] [WHERE expr]`（无 WHERE 作用于全表） |
| 删除 | `DELETE FROM name [WHERE expr]`（无 WHERE 清空全表） |
| 查询 | `SELECT [DISTINCT] expr [AS alias], ... FROM name [WHERE expr] [GROUP BY expr, ...] [HAVING expr] [ORDER BY expr [ASC\|DESC], ...] [LIMIT n [OFFSET m]]` |
| 投影 | 指定列、`*` 通配、`AS` 别名（`ORDER BY` 可引用别名） |
| 表达式 | 比较 `= != < <= > >=`、逻辑 `AND OR NOT`、算术 `+ - * /`、括号、`IS NULL` / `IS NOT NULL`、一元负号 |
| 聚合 | `COUNT SUM AVG MIN MAX`，支持 `COUNT(*)`，配合 `GROUP BY` / `HAVING` |

字面量：整数、浮点数、单引号字符串、`NULL`。

## 语义约定

- **三值逻辑**：任何与缺失值（NULL）的比较结果为"未知"，不满足 WHERE；`AND`/`OR`/`NOT` 按 SQL 三值逻辑传播未知。
- **聚合忽略缺失值**：`COUNT(col)` 不计 NULL，`SUM`/`AVG`/`MIN`/`MAX` 跳过 NULL；空集上 `COUNT` 为 0，其余为 NULL。
- **GROUP BY** 将所有缺失值归为同一组。
- **排序**：多列排序键按声明顺序比较；NULL 在 `ASC` 时排最前、`DESC` 时排最后。
- **类型检查**：`INTEGER` 列只接受整数，`REAL` 接受整数/浮点（统一存为浮点），`TEXT` 只接受字符串；对 TEXT 列做 `SUM`/`AVG`、字符串与数字比较、文本参与算术、除以零都会抛出 `StorelensError`。
- **主键**：主键列不允许 NULL 和重复值（INSERT / UPDATE / JSON 导入均校验）。
- 标识符（表名、列名）大小写敏感；关键字大小写不敏感。

## 错误处理

所有语法错误（未知关键字、缺分号、括号不匹配、非法字符、字符串未闭合等）与语义错误（引用不存在的数据集/列、类型不匹配、主键冲突、聚合函数误用等）统一抛出 `storelens.StorelensError`，消息带明确说明；语法错误附带行号/列号。不静默失败，不抛裸异常。

## 架构设计

```
storelens/
├── errors.py        StorelensError（统一异常，可携带行列号）
├── lexer.py         词法分析器：文本 -> Token 流（关键字归一化大写、字符串转义、行列跟踪）
├── astnodes.py      AST 节点定义（表达式 / 语句）与聚合函数检测
├── parser.py        递归下降解析器：Token 流 -> AST
│                    优先级：OR < AND < NOT < 比较/IS NULL < +- < */ < 一元负号 < 原子
├── tables.py        类型系统（INTEGER/REAL/TEXT 校验与 coercion）与内存表（有序行、主键约束）
├── expressions.py   表达式求值：三值逻辑、NULL 传播、聚合函数（按组求值）
├── engine.py        执行器 Engine：DDL/DML/SELECT 执行、分组/去重/排序/分页、JSON 导入
├── cli.py           命令行：REPL、格式化表格输出、元命令、脚本文件批量执行
└── __main__.py      支持 python3 -m storelens
tests/               pytest 测试（词法/语法边界、表达式、聚合、排序分页、DML、错误、导入、CLI）
storelens-cli        可执行启动脚本（免安装直接运行）
```

数据流：`文本 --lexer--> Token 流 --parser--> AST --engine 执行--> Result(columns, rows)`。
SELECT 执行顺序：WHERE 过滤 → （可选）分组 → 投影/聚合 → HAVING → DISTINCT → ORDER BY → OFFSET/LIMIT。

## 运行测试

```bash
python3 -m pytest tests/ -v
```
