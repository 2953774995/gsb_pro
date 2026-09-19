# sqlq

A minimal, in-memory relational SQL query engine implemented from scratch in
Python.  **Standard library only** — the engine has no third-party
dependencies (`pytest` is used solely for the test suite).

sqlq includes its own tokenizer, recursive-descent parser, expression
evaluator with SQL three-valued logic, semantic analyzer and row-based
execution engine, plus an interactive CLI.

## Features

- Hand-written **lexer** (line/column tracking, `--` and `/* */` comments,
  escaped string literals `'it''s'`, integer/float/exponent numbers)
- Hand-written **recursive-descent parser** producing an explicit AST
- Statements: `CREATE TABLE`, `DROP TABLE`, `INSERT`, `UPDATE`, `DELETE`,
  `SELECT`; every statement ends with `;`; keywords are case-insensitive
- Data types: `INTEGER`, `REAL`, `TEXT`
- Constraints: `PRIMARY KEY` (uniqueness + implicit NOT NULL) and
  column-level `NOT NULL`
- Projection: explicit columns, `*` / `table.*`, aliases with `AS`
- `WHERE`: arithmetic, comparisons (`= != <> < <= > >=`), boolean
  `AND OR NOT`, parentheses, dictionary-ordered string comparison,
  `IS NULL` / `IS NOT NULL`
- Aggregates: `COUNT` (incl. `COUNT(*)` / `COUNT(DISTINCT …)`), `SUM`,
  `AVG`, `MIN`, `MAX`, with `GROUP BY` (multi-column, NULLs form one group)
  and `HAVING`
- `DISTINCT`, `ORDER BY` (multi-key, `ASC`/`DESC`, NULL ordering),
  `LIMIT` / `OFFSET`
- SQL **NULL semantics**: comparisons with NULL yield UNKNOWN (rows fail
  `WHERE`), arithmetic propagates NULL, aggregates ignore NULL,
  `GROUP BY`/`DISTINCT` treat NULLs as equal
- Strict type checking: storing a TEXT into an INTEGER column, `SUM`/`AVG`
  over a TEXT column, division by zero, etc. raise a descriptive
  `SqlqError` — nothing fails silently

> JOIN is intentionally not implemented; queries that mention `JOIN` (and
> other reserved but unsupported syntax like `IN`, `BETWEEN`, `LIKE`,
> `UNION`) are rejected with a clear syntax error.

## Architecture

```
sqlq/
├── errors.py     # SqlqError / SqlqSyntaxError (with line:column)
├── values.py     # INTEGER/REAL/TEXT primitives, NULL, type coercion
├── lexer.py      # tokenizer: source text -> Token stream
├── ast_nodes.py  # AST definitions for statements and expressions
├── parser.py     # recursive-descent parser: tokens -> AST
├── evaluator.py  # scalar expression evaluation, 3-valued logic
├── analyzer.py   # semantic checks: names, aggregates, types, LIMIT
├── table.py      # in-memory Table / Column storage (ordered rows)
├── engine.py     # Engine API, execution for every statement, ResultSet
├── cli.py        # REPL + file batch runner + ASCII table renderer
└── __main__.py   # `python3 -m sqlq`
```

Data flow for one query:

```
SQL text ──lexer──▶ Tokens ──parser──▶ AST ──analyzer──▶ validated AST
                                                          │
                                                      engine
                                                          ▼
                                            ResultSet(columns, rows)
```

Execution model: `SELECT` scans the (single) table, applies `WHERE`, then
either projects rows directly or partitions them into groups for
aggregates. Aggregate results are keyed by AST node id, so the same
`FuncCall` node is evaluated once per group and can be referenced from
`SELECT`, `HAVING` and `ORDER BY`. Sorting uses a stable comparator that
implements SQL NULL ordering (NULLs first on ASC, last on DESC).

## Supported SQL grammar (summary)

```
statement := create | drop | insert | update | delete | select
create    := CREATE TABLE name ( col type [PRIMARY KEY] [NOT NULL] {, ...} )
drop      := DROP TABLE name
insert    := INSERT INTO name [( col {, ...} )] VALUES ( expr {, ...} )
update    := UPDATE name SET col = expr {, ...} [WHERE expr]
delete    := DELETE FROM name [WHERE expr]
select    := SELECT [DISTINCT] item {, ...} [FROM name]
             [WHERE expr] [GROUP BY expr {, ...}] [HAVING expr]
             [ORDER BY expr [ASC|DESC] {, ...}]
             [LIMIT const] [OFFSET const]
item      := * | name.* | expr [AS alias]
expr      := OR < AND < NOT < comparison (=,!=,<>,<,<=,>,>=, IS [NOT] NULL)
             < additive (+,-) < multiplicative (*,/,%) < unary (-,+) < primary
primary   := integer | float | 'text' | NULL | TRUE | FALSE
           | col | name.col | ( expr )
           | COUNT(*) | {COUNT|SUM|AVG|MIN|MAX}([DISTINCT] expr)
```

## Usage

### Python API

```python
from sqlq import Engine

engine = Engine()
engine.execute_script("""
    CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price REAL);
    INSERT INTO products VALUES (1, 'keyboard', 199.5);
    INSERT INTO products VALUES (2, 'mouse', 79.0);
""")

result = engine.execute("""
    SELECT name, price FROM products
    WHERE price > 100 ORDER BY price DESC LIMIT 5
""")
print(result.columns)   # ['name', 'price']
for row in result.rows:  # [('keyboard', 199.5)]
    print(row)
```

`execute(sql)` runs one statement and returns a `ResultSet`
(`.columns`, `.rows`, `.rowcount`, `.statement_type`, `.as_dicts()`).
`execute_script(sql_text)` runs multiple `;`-terminated statements and
returns a list of results. All errors derive from `sqlq.SqlqError`
(syntax errors from `SqlqSyntaxError`) and carry an explanatory message,
often with `line`/`column`.

### CLI

```bash
# interactive shell
python3 -m sqlq

# execute one or more SQL files
python3 -m sqlq schema.sql queries.sql

# pipe SQL in
echo "SELECT 1 + 1;" | python3 -m sqlq -

# convenience launcher (no installation needed)
./sqlq-cli.py
```

Interactive example:

```
sqlq> CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT, v INTEGER);
CREATE TABLE t
sqlq> INSERT INTO t VALUES (1, 'a', 10);
INSERT 1
sqlq> SELECT name, v * 2 AS dbl FROM t ORDER BY v DESC;
+------+-----+
| name | dbl |
+------+-----+
| a    | 20  |
+------+-----+
(1 rows)
sqlq> .tables
t
sqlq> .exit
```

The REPL also supports `.schema [TABLE]`, `.help`, `.exit`/`.quit` and
recovers cleanly after an error.

## Installation (optional)

The package can also be installed, which exposes the `sqlq-cli` script:

```bash
pip install .
sqlq-cli queries.sql
```

## Testing

```bash
python3 -m pytest tests/ -v
```

The suite (150+ tests) covers:

- lexer and parser edge cases (unterminated strings/comments, missing
  semicolons, unbalanced parentheses, unknown keywords/functions,
  operator precedence)
- expression evaluation incl. precedence, unary operators and full NULL
  three-valued logic truth tables
- DDL, type coercion, PRIMARY KEY / NOT NULL conflicts
- INSERT / UPDATE / DELETE semantics, self-referencing updates
- aggregates, `GROUP BY` (incl. NULL groups, multiple keys), `HAVING`,
  `DISTINCT` aggregates, empty-table boundaries, TEXT type misuse
- `ORDER BY` (multi-key, ASC/DESC, NULL placement), `LIMIT`/`OFFSET`
- `DISTINCT`, empty tables and empty result sets
- the CLI renderer, REPL (including error recovery) and file/stdin batch
  mode
