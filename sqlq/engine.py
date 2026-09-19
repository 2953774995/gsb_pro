"""Execution engine: plans statements and runs them against in-memory tables."""

from functools import cmp_to_key

from . import ast_nodes as ast
from . import analyzer
from .errors import SqlqError
from .evaluator import evaluate, is_true
from .parser import parse, parse_script
from .table import Table
from .values import INTEGER, REAL, TEXT, NULL, coerce_for_column, type_name_of


class ResultSet:
    """Result of executing a statement.

    For SELECT the column names and rows are populated; DDL/DML statements
    return an empty result set carrying a short ``message`` and a
    ``rowcount`` (rows inserted/updated/deleted, else None).
    """

    __slots__ = ("columns", "rows", "message", "rowcount", "statement_type")

    def __init__(self, columns=None, rows=None, message="OK", rowcount=None,
                 statement_type=None):
        self.columns = columns or []
        self.rows = list(rows or [])
        self.message = message
        self.rowcount = rowcount
        self.statement_type = statement_type

    def __iter__(self):
        return iter(self.rows)

    def __len__(self):
        return len(self.rows)

    def as_dicts(self):
        return [dict(zip(self.columns, row)) for row in self.rows]

    def __repr__(self):
        return f"ResultSet(columns={self.columns!r}, rows={len(self.rows)})"


class Engine:
    """In-memory SQL engine.  Create one instance per database session."""

    def __init__(self):
        self.tables = {}

    # -- public API --------------------------------------------------------

    def execute(self, sql):
        statement = parse(sql)
        analyzer.analyze(statement, self.tables)
        return self._run(statement)

    def execute_script(self, sql_text):
        statements = parse_script(sql_text)
        if not statements:
            return []
        results = []
        for statement in statements:
            analyzer.analyze(statement, self.tables)
            results.append(self._run(statement))
        return results

    def table_names(self):
        return sorted(self.tables)

    # -- dispatch ----------------------------------------------------------

    def _run(self, statement):
        if isinstance(statement, ast.CreateTable):
            return self._run_create(statement)
        if isinstance(statement, ast.DropTable):
            return self._run_drop(statement)
        if isinstance(statement, ast.Insert):
            return self._run_insert(statement)
        if isinstance(statement, ast.Update):
            return self._run_update(statement)
        if isinstance(statement, ast.Delete):
            return self._run_delete(statement)
        if isinstance(statement, ast.Select):
            return self._run_select(statement)
        raise SqlqError(f"unsupported statement {type(statement).__name__}")

    # -- DDL ---------------------------------------------------------------

    def _run_create(self, statement):
        if statement.table in self.tables:
            raise SqlqError(f"table {statement.table!r} already exists")
        self.tables[statement.table] = Table(statement.table, statement.columns)
        return ResultSet(message=f"CREATE TABLE {statement.table}",
                         statement_type="CREATE")

    def _run_drop(self, statement):
        del self.tables[statement.table]
        return ResultSet(message=f"DROP TABLE {statement.table}",
                         statement_type="DROP")

    # -- INSERT ------------------------------------------------------------

    def _run_insert(self, statement):
        table = self.tables[statement.table]
        if statement.columns is None:
            target = table.columns
        else:
            target = [table.column(name) for name in statement.columns]
        row = [None] * len(table.columns)
        provided = set()
        for value_expr, column in zip(statement.values, target):
            raw = evaluate(value_expr, {})
            row[table.index(column.name)] = coerce_for_column(raw, column.data_type)
            provided.add(column.name)
        for column in table.columns:
            if column.name not in provided:
                row[table.index(column.name)] = None
        self._check_nullability(table, row)
        self._check_primary_key(table, row, exclude_row=None)
        table.rows.append(tuple(row))
        return ResultSet(message="INSERT 1", rowcount=1, statement_type="INSERT")

    def _check_nullability(self, table, candidate):
        for column in table.columns:
            if column.not_null and candidate[table.index(column.name)] is None:
                kind = "primary key" if column.primary_key else "NOT NULL"
                raise SqlqError(
                    f"null value in {kind} column {column.name!r} is not allowed"
                )

    def _check_primary_key(self, table, candidate, exclude_row):
        pk = table.primary_key
        if pk is None:
            return
        value = candidate[table.index(pk.name)]
        if value is None:
            raise SqlqError(
                f"null value in primary key column {pk.name!r} is not allowed"
            )
        for existing in table.rows:
            if existing is exclude_row:
                continue
            if existing[table.index(pk.name)] == value:
                raise SqlqError(
                    f"primary key constraint violation: duplicate value {value!r} "
                    f"in column {pk.name!r}"
                )

    # -- UPDATE / DELETE ---------------------------------------------------

    def _row_context(self, table, row):
        context = dict(zip(table.column_names, row))
        # Qualified names are supported as well.
        for name, value in zip(table.column_names, row):
            context[f"{table.name}.{name}"] = value
        return context

    def _run_update(self, statement):
        table = self.tables[statement.table]
        contexts = [(idx, row) for idx, row in enumerate(table.rows)]
        matched = []
        for idx, row in contexts:
            context = self._row_context(table, row)
            if statement.where is None or is_true(evaluate(statement.where, context)):
                matched.append((idx, row, context))

        # Build new rows first so constraint/type errors abort without partial
        # application.
        new_rows = list(table.rows)
        for idx, old_row, context in matched:
            row = list(old_row)
            for column_name, value_expr in statement.assignments:
                column = table.column(column_name)
                raw = evaluate(value_expr, context)
                row[table.index(column_name)] = coerce_for_column(raw, column.data_type)
            new_rows[idx] = tuple(row)

        for idx, _, _ in matched:
            self._check_nullability(table, new_rows[idx])
            self._check_primary_key(table, new_rows[idx], exclude_row=table.rows[idx])
        table.rows = new_rows
        return ResultSet(message=f"UPDATE {len(matched)}", rowcount=len(matched),
                         statement_type="UPDATE")

    def _run_delete(self, statement):
        table = self.tables[statement.table]
        surviving = []
        removed = 0
        for row in table.rows:
            context = self._row_context(table, row)
            match = statement.where is None or is_true(
                evaluate(statement.where, context)
            )
            if match:
                removed += 1
            else:
                surviving.append(row)
        table.rows = surviving
        return ResultSet(message=f"DELETE {removed}", rowcount=removed,
                         statement_type="DELETE")

    # -- SELECT ------------------------------------------------------------

    def _run_select(self, statement):
        table = self.tables.get(statement.table) if statement.table else None
        source_rows = []
        if table is not None:
            for row in table.rows:
                if statement.where is None or is_true(
                    evaluate(statement.where, self._row_context(table, row))
                ):
                    source_rows.append((row, self._row_context(table, row)))
        elif statement.where is not None:
            if is_true(evaluate(statement.where, {})):
                source_rows.append(((), {}))
        else:
            source_rows.append(((), {}))

        aggregate_nodes = getattr(statement, "_aggregates", [])
        grouped = getattr(statement, "_grouped", False)

        if grouped or aggregate_nodes:
            output_rows, output_contexts = self._run_grouped(
                statement, table, source_rows, aggregate_nodes
            )
        else:
            output_rows = []
            output_contexts = []
            for _, context in source_rows:
                output_rows.append(
                    tuple(evaluate(item.expr, context) for item in statement.items)
                )
                output_contexts.append(context)

        columns = [
            item.alias if item.alias is not None else analyzer.output_label(item.expr)
            for item in statement.items
        ]

        # DISTINCT (applied before ORDER/LIMIT, preserving first occurrence).
        if statement.distinct:
            seen = set()
            deduped = []
            deduped_contexts = []
            for row, context in zip(output_rows, output_contexts):
                key = _hashable(row)
                if key not in seen:
                    seen.add(key)
                    deduped.append(row)
                    deduped_contexts.append(context)
            output_rows = deduped
            output_contexts = deduped_contexts

        # ORDER BY.
        if statement.order_by:
            output_rows, output_contexts = self._order_rows(
                statement, table, output_rows, output_contexts
            )

        # OFFSET / LIMIT.
        if statement.offset is not None:
            offset_value = evaluate(statement.offset, {})
            offset = _non_negative_int(offset_value, "OFFSET")
        else:
            offset = 0
        if statement.limit is not None:
            limit_value = evaluate(statement.limit, {})
            limit = _non_negative_int(limit_value, "LIMIT")
            output_rows = output_rows[offset:offset + limit]
        elif offset:
            output_rows = output_rows[offset:]

        return ResultSet(columns=columns, rows=output_rows,
                         statement_type="SELECT")

    def _run_grouped(self, statement, table, source_rows, aggregate_nodes):
        groups = self._partition(statement, source_rows)

        output_rows = []
        output_contexts = []
        # A grand-total aggregate over zero rows still yields one output row.
        if not groups and not statement.group_by:
            groups = [((), [])]

        for group_key, members in groups:
            group_context = self._group_context(table, group_key, members,
                                                statement.group_by)
            aggregate_values = self._compute_aggregates(
                aggregate_nodes, members
            )
            # HAVING filter.
            if statement.having is not None:
                ok = evaluate(statement.having, group_context, aggregate_values)
                if not is_true(ok):
                    continue
            output_rows.append(
                tuple(
                    evaluate(item.expr, group_context, aggregate_values)
                    for item in statement.items
                )
            )
            # Context for ORDER BY: group columns + aggregate results
            # keyed by node id so evaluate() can resolve any FuncCall node.
            order_context = dict(group_context)
            for node in aggregate_nodes:
                order_context[id(node)] = aggregate_values[id(node)]
            output_contexts.append(order_context)
        return output_rows, output_contexts

    def _partition(self, statement, source_rows):
        if not statement.group_by:
            return [((), source_rows)]
        groups = {}
        raw_values = {}
        order = []
        for row, context in source_rows:
            key_values = tuple(
                evaluate(expr, context) for expr in statement.group_by
            )
            hash_key = _hashable(key_values)
            if hash_key not in groups:
                groups[hash_key] = []
                raw_values[hash_key] = key_values
                order.append(hash_key)
            groups[hash_key].append((row, context))
        return [(raw_values[key], groups[key]) for key in order]

    def _group_context(self, table, group_key, members, group_exprs):
        context = {}
        if group_exprs:
            for expr, value in zip(group_exprs, group_key):
                if isinstance(expr, ast.ColumnRef):
                    context[expr.column] = value
                    if table is not None:
                        context[f"{table.name}.{expr.column}"] = value
        return context

    def _compute_aggregates(self, aggregate_nodes, members):
        values = {}
        for node in aggregate_nodes:
            values[id(node)] = self._aggregate_one(node, members)
        return values

    def _aggregate_one(self, node, members):
        if node.star:
            return len(members)
        evaluated = []
        for _, context in members:
            value = evaluate(node.arg, context)
            if value is not None:
                evaluated.append(value)
        if node.distinct:
            evaluated = _distinct_values(evaluated)
        name = node.name
        if name == "COUNT":
            return len(evaluated)
        if not evaluated:
            return None
        if name == "SUM":
            return sum(evaluated)
        if name == "AVG":
            total = sum(evaluated)
            return total / len(evaluated)
        if name == "MIN":
            return min(evaluated)
        if name == "MAX":
            return max(evaluated)
        raise SqlqError(f"unknown aggregate {name}")

    def _order_rows(self, statement, table, rows, contexts):
        """Sort projected rows.

        Each ORDER BY expression is resolved in this order:
        1. an output column alias/default name (matched by analyzer);
        2. an aggregate result (grouped queries);
        3. a source-table column that still exists in the row context.
        """
        output_names = _output_names(statement)

        def key_values(row, context):
            values = []
            aggregate_values = {
                key: val for key, val in context.items() if isinstance(key, int)
            }
            merged = {
                key: val for key, val in context.items() if not isinstance(key, int)
            }
            # Output column names shadow source columns in case of collision.
            for name, value in zip(output_names, row):
                merged[name] = value
            for order_key in statement.order_by:
                values.append(
                    evaluate(order_key.expr, merged, aggregate_values)
                )
            return values

        decorated = list(zip(rows, contexts))
        decorated.sort(key=lambda _: 0)
        for position in reversed(range(len(statement.order_by))):
            descending = statement.order_by[position].descending
            decorated = sorted(
                decorated,
                key=cmp_to_key(_make_comparator(
                    lambda pair, pos=position:
                        key_values(pair[0], pair[1])[pos],
                    descending,
                )),
            )
        return [row for row, _ in decorated], [ctx for _, ctx in decorated]

def _output_names(statement):
    names = []
    for item in statement.items:
        names.append(
            item.alias if item.alias is not None
            else analyzer.output_label(item.expr)
        )
    return names


def _make_comparator(getter, descending):
    def compare(left_pair, right_pair):
        left = getter(left_pair)
        right = getter(right_pair)
        if left is None and right is None:
            return 0
        if left is None:
            return 1 if descending else -1
        if right is None:
            return -1 if descending else 1
        if left < right:
            return 1 if descending else -1
        if left > right:
            return -1 if descending else 1
        return 0
    return compare


def _hashable(values):
    result = []
    for value in values:
        try:
            hash(value)
            result.append(("v", value))
        except TypeError:
            result.append(("r", repr(value)))
    return tuple(result)


def _distinct_values(values):
    seen = set()
    out = []
    for value in values:
        key = _hashable([value])
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _non_negative_int(value, what):
    if isinstance(value, bool) or not isinstance(value, int):
        raise SqlqError(f"{what} must be an integer")
    if value < 0:
        raise SqlqError(f"{what} must not be negative")
    return value
