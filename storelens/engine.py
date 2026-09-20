"""Query engine: executes parsed statements against in-memory tables."""

import json

from .errors import StorelensError
from .parser import parse_script, AGGREGATE_FUNCTIONS
from .table import Table
from .expressions import RowContext, evaluate, matches
from .ast_nodes import (CreateTable, DropTable, Insert, Update, Delete,
                        Select, Column, Star, FuncCall, Literal, UnaryOp,
                        BinaryOp, IsNull)
from .types import is_number


class Result:
    """The outcome of executing one statement.

    For SELECT, ``columns`` and ``rows`` hold the result set. For other
    statements ``message`` describes the effect and ``affected`` counts
    the rows touched.
    """

    def __init__(self, columns=None, rows=None, message="", affected=0):
        self.columns = columns or []
        self.rows = rows or []
        self.message = message
        self.affected = affected

    def __repr__(self):
        return "Result(columns=%r, rows=%r)" % (self.columns, self.rows)


def _find_aggregates(expr, found):
    """Collect FuncCall nodes in an expression tree."""
    if isinstance(expr, FuncCall):
        found.append(expr)
        for arg in expr.args:
            _find_aggregates(arg, found)
    elif isinstance(expr, UnaryOp):
        _find_aggregates(expr.operand, found)
    elif isinstance(expr, BinaryOp):
        _find_aggregates(expr.left, found)
        _find_aggregates(expr.right, found)
    elif isinstance(expr, IsNull):
        _find_aggregates(expr.operand, found)


class Engine:
    def __init__(self):
        self._tables = {}  # lower-cased name -> Table

    # -- public API ---------------------------------------------------------

    @property
    def tables(self):
        return [t.name for t in self._tables.values()]

    def get_table(self, name):
        table = self._tables.get(name.lower())
        if table is None:
            raise StorelensError("Unknown table '%s'" % name)
        return table

    def execute(self, query):
        """Execute a single statement and return a Result."""
        statements = parse_script(query)
        if len(statements) != 1:
            raise StorelensError(
                "execute() expects exactly one statement, got %d"
                % len(statements))
        return self._execute_statement(statements[0])

    def execute_script(self, text):
        """Execute multiple semicolon-separated statements.

        Returns the list of Results, one per statement. Execution stops
        at the first error.
        """
        results = []
        for stmt in parse_script(text):
            results.append(self._execute_statement(stmt))
        return results

    def import_json(self, table_name, source):
        """Bulk-import rows from a JSON file (or parsed list) into a table.

        The JSON document must be an array of objects whose keys are
        column names of the target table. Returns the number of rows
        imported. The import is atomic: on any error the table is left
        unchanged.
        """
        table = self.get_table(table_name)
        if isinstance(source, str):
            try:
                with open(source, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except FileNotFoundError:
                raise StorelensError("JSON file not found: %s" % source)
            except json.JSONDecodeError as exc:
                raise StorelensError("Invalid JSON in %s: %s" % (source, exc))
        else:
            data = source
        if isinstance(data, dict):
            # tolerate {"rows": [...]} style exports
            lists = [v for v in data.values() if isinstance(v, list)]
            if len(lists) == 1:
                data = lists[0]
        if not isinstance(data, list):
            raise StorelensError(
                "JSON import expects an array of objects for table '%s'"
                % table.name)
        new_rows = []
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                raise StorelensError(
                    "JSON import row %d is not an object" % (i + 1))
            for key in item:
                if not table.has_column(key):
                    raise StorelensError(
                        "JSON import row %d references unknown column '%s' "
                        "in table '%s'" % (i + 1, key, table.name))
            row = table.make_row(list(item.values()), list(item.keys()))
            new_rows.append(row)
        # Validate primary keys across existing + new rows before inserting.
        staged = list(table.rows)
        for row in new_rows:
            staged.append(row)
            if table.primary_key is not None:
                idx = table.column_index(table.primary_key)
                value = row[idx]
                if value is None:
                    raise StorelensError(
                        "JSON import: primary key column '%s' cannot be NULL"
                        % table.primary_key)
                seen = sum(1 for r in staged if r[idx] == value)
                if seen > 1:
                    raise StorelensError(
                        "Primary key violation: duplicate value %r for "
                        "column '%s' in table '%s'"
                        % (value, table.primary_key, table.name))
        table.rows.extend(new_rows)
        return len(new_rows)

    # -- statement dispatch ---------------------------------------------------

    def _execute_statement(self, stmt):
        if isinstance(stmt, CreateTable):
            return self._execute_create(stmt)
        if isinstance(stmt, DropTable):
            return self._execute_drop(stmt)
        if isinstance(stmt, Insert):
            return self._execute_insert(stmt)
        if isinstance(stmt, Update):
            return self._execute_update(stmt)
        if isinstance(stmt, Delete):
            return self._execute_delete(stmt)
        if isinstance(stmt, Select):
            return self._execute_select(stmt)
        raise StorelensError("Unsupported statement: %r" % (stmt,))

    def _execute_create(self, stmt):
        if stmt.name.lower() in self._tables:
            raise StorelensError("Table '%s' already exists" % stmt.name)
        table = Table(stmt.name, stmt.columns)
        self._tables[stmt.name.lower()] = table
        cols = ", ".join("%s %s%s" % (
            c.name, c.type_name,
            " PRIMARY KEY" if c.primary_key else "") for c in table.columns)
        return Result(message="Table '%s' created (%s)" % (table.name, cols))

    def _execute_drop(self, stmt):
        table = self.get_table(stmt.name)
        del self._tables[table.name.lower()]
        return Result(message="Table '%s' dropped" % table.name)

    def _execute_insert(self, stmt):
        table = self.get_table(stmt.table)
        if stmt.columns is not None:
            lowered = [c.lower() for c in stmt.columns]
            if len(set(lowered)) != len(lowered):
                raise StorelensError(
                    "Duplicate column in INSERT column list for table '%s'"
                    % table.name)
            for c in stmt.columns:
                table.column_index(c)  # validate existence
        rows = []
        for value_exprs in stmt.rows:
            values = [evaluate(e, RowContext(table, ()))
                      for e in value_exprs]
            rows.append(table.make_row(values, stmt.columns))
        for row in rows:
            table.insert_row(row)
        return Result(message="%d row(s) inserted into '%s'"
                      % (len(rows), table.name), affected=len(rows))

    def _execute_update(self, stmt):
        table = self.get_table(stmt.table)
        indices = [table.column_index(col) for col, _ in stmt.assignments]
        changed = 0
        for pos, row in enumerate(table.rows):
            ctx = RowContext(table, row)
            if stmt.where is not None and not matches(
                    evaluate(stmt.where, ctx)):
                continue
            # New values are computed against the original row.
            new_values = [table.coerce_value(col, evaluate(expr, ctx))
                          for col, expr in stmt.assignments]
            new_row = list(row)
            for idx, value in zip(indices, new_values):
                new_row[idx] = value
            new_row = tuple(new_row)
            table.check_row_primary_key(new_row, exclude_row=row)
            table.rows[pos] = new_row
            changed += 1
        return Result(message="%d row(s) updated in '%s'"
                      % (changed, table.name), affected=changed)

    def _execute_delete(self, stmt):
        table = self.get_table(stmt.table)
        kept = []
        deleted = 0
        for row in table.rows:
            if stmt.where is None or matches(
                    evaluate(stmt.where, RowContext(table, row))):
                deleted += 1
            else:
                kept.append(row)
        table.rows = kept
        return Result(message="%d row(s) deleted from '%s'"
                      % (deleted, table.name), affected=deleted)

    # -- SELECT ---------------------------------------------------------------

    def _execute_select(self, stmt):
        table = self.get_table(stmt.table)

        # Expand * in the select list.
        items = []
        for item in stmt.items:
            if isinstance(item.expr, Star):
                for name in table.column_names:
                    items.append(type(item)(Column(name)))
            else:
                items.append(item)

        # WHERE filtering.
        filtered = [row for row in table.rows
                    if stmt.where is None or matches(
                        evaluate(stmt.where, RowContext(table, row)))]

        # Detect aggregate usage.
        aggregates = []
        for item in items:
            _find_aggregates(item.expr, aggregates)
        if stmt.having is not None:
            _find_aggregates(stmt.having, aggregates)
        for order_item in stmt.order_by:
            _find_aggregates(order_item.expr, aggregates)
        is_aggregate = bool(aggregates) or bool(stmt.group_by)
        for func in aggregates:
            if func.name not in AGGREGATE_FUNCTIONS:
                raise StorelensError("Unknown function '%s'" % func.name)

        # entries: list of (output_row, sort_context)
        if is_aggregate:
            entries, out_names = self._run_aggregate(
                table, items, filtered, stmt)
        else:
            entries, out_names = self._run_projection(table, items, filtered)

        # DISTINCT
        if stmt.distinct:
            seen = set()
            unique = []
            for out_row, ctx in entries:
                if out_row not in seen:
                    seen.add(out_row)
                    unique.append((out_row, ctx))
            entries = unique

        # ORDER BY
        if stmt.order_by:
            entries = self._apply_order_by(entries, stmt.order_by,
                                           out_names, table)

        # LIMIT / OFFSET
        rows = [out_row for out_row, _ in entries]
        if stmt.offset:
            rows = rows[stmt.offset:]
        if stmt.limit is not None:
            rows = rows[:stmt.limit]

        return Result(columns=out_names, rows=rows)

    def _run_projection(self, table, items, rows):
        out_names = []
        for item in items:
            out_names.append(item.alias or self._default_name(item.expr))
        entries = []
        for row in rows:
            ctx = RowContext(table, row)
            out = tuple(evaluate(item.expr, ctx) for item in items)
            entries.append((out, ctx))
        return entries, out_names

    def _run_aggregate(self, table, items, rows, stmt):
        out_names = []
        for item in items:
            out_names.append(item.alias or self._default_name(item.expr))

        # Group rows.
        groups = {}   # key -> list of rows
        order = []    # preserve first-seen group order
        if stmt.group_by:
            for row in rows:
                ctx = RowContext(table, row)
                key = tuple(evaluate(g, ctx) for g in stmt.group_by)
                if key not in groups:
                    groups[key] = []
                    order.append(key)
                groups[key].append(row)
        else:
            # Whole result set is a single group (even when empty).
            groups[()] = list(rows)
            order.append(())

        entries = []
        for key in order:
            group_rows = groups[key]
            agg_values = {}
            # Collect aggregates from select list + having.
            funcs = []
            for item in items:
                _find_aggregates(item.expr, funcs)
            if stmt.having is not None:
                _find_aggregates(stmt.having, funcs)
            for order_item in stmt.order_by:
                _find_aggregates(order_item.expr, funcs)
            for func in funcs:
                if id(func) not in agg_values:
                    agg_values[id(func)] = self._compute_aggregate(
                        func, table, group_rows)
            base_row = group_rows[0] if group_rows else \
                (None,) * len(table.columns)
            ctx = RowContext(table, base_row, agg_values)
            if stmt.having is not None and not matches(
                    evaluate(stmt.having, ctx)):
                continue
            out = tuple(evaluate(item.expr, ctx) for item in items)
            entries.append((out, ctx))
        return entries, out_names

    def _compute_aggregate(self, func, table, rows):
        name = func.name
        if name == "COUNT":
            if func.star:
                return len(rows)
            if len(func.args) != 1:
                raise StorelensError("COUNT expects exactly one argument")
            count = 0
            for row in rows:
                if evaluate(func.args[0], RowContext(table, row)) is not None:
                    count += 1
            return count
        if func.star:
            raise StorelensError("%s(*) is not supported; use COUNT(*)"
                                 % name)
        if len(func.args) != 1:
            raise StorelensError("%s expects exactly one argument" % name)
        values = []
        for row in rows:
            value = evaluate(func.args[0], RowContext(table, row))
            if value is not None:
                values.append(value)  # aggregates ignore missing values
        if name in ("SUM", "AVG"):
            for value in values:
                if not is_number(value):
                    raise StorelensError(
                        "Type mismatch: %s requires numeric values, got %r"
                        % (name, value))
            if not values:
                return None
            total = sum(values)
            if name == "SUM":
                return total
            return total / len(values)
        # MIN / MAX work on numbers and text.
        if not values:
            return None
        first = values[0]
        for value in values:
            if is_number(first) != is_number(value):
                raise StorelensError(
                    "Type mismatch: %s cannot mix numeric and text values"
                    % name)
        return min(values) if name == "MIN" else max(values)

    def _apply_order_by(self, entries, order_by, out_names, table):
        def key_value(order_item, entry):
            out_row, ctx = entry
            expr = order_item.expr
            if isinstance(expr, Column):
                for i, name in enumerate(out_names):
                    if name.lower() == expr.name.lower():
                        return out_row[i]
            return evaluate(expr, ctx)

        def sortable(value):
            # None (missing) always sorts last; numbers before text.
            if is_number(value):
                return (0, float(value))
            return (1, str(value))

        result = list(entries)
        for order_item in reversed(order_by):
            nulls = [e for e in result
                     if key_value(order_item, e) is None]
            non_nulls = [e for e in result
                         if key_value(order_item, e) is not None]
            non_nulls.sort(
                key=lambda e: sortable(key_value(order_item, e)),
                reverse=order_item.descending)
            result = non_nulls + nulls
        return result

    @staticmethod
    def _default_name(expr):
        if isinstance(expr, Column):
            return expr.name
        if isinstance(expr, FuncCall):
            inner = "*" if expr.star else ", ".join(
                Engine._default_name(a) for a in expr.args)
            return "%s(%s)" % (expr.name, inner)
        if isinstance(expr, Literal):
            return repr(expr.value)
        if isinstance(expr, UnaryOp):
            return "%s %s" % (expr.op, Engine._default_name(expr.operand))
        if isinstance(expr, BinaryOp):
            return "%s %s %s" % (Engine._default_name(expr.left), expr.op,
                                 Engine._default_name(expr.right))
        if isinstance(expr, IsNull):
            return "%s IS %sNULL" % (Engine._default_name(expr.operand),
                                     "NOT " if expr.negated else "")
        return "expr"
