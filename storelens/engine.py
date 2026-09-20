"""The storelens execution engine.

Holds the in-memory catalog of tables and executes parsed statements.
Public API:

    engine = Engine()
    result = engine.execute("SELECT * FROM orders;")
    results = engine.execute_script("CREATE TABLE ...; INSERT ...;")
    count = engine.import_json("orders", "orders.json")

A Result has .columns (list of names), .rows (list of tuples), plus
.message / .rowcount for non-SELECT statements.
"""

import json
from functools import cmp_to_key

from . import astnodes as ast
from .errors import StorelensError
from .expressions import evaluate, _truthy
from .parser import parse, parse_one
from .tables import Column, Table, is_number


class Result:
    def __init__(self, columns=None, rows=None, message=None, rowcount=0):
        self.columns = columns or []
        self.rows = rows or []
        self.message = message
        self.rowcount = rowcount

    def __repr__(self):
        return "Result(columns=%r, rows=%r)" % (self.columns, self.rows)


class Engine:
    def __init__(self):
        self.tables = {}

    # ---------- public API ----------

    def execute(self, query):
        """Execute a single statement and return a Result."""
        statement = parse_one(query)
        return self._execute(statement)

    def execute_script(self, text):
        """Execute several ';'-terminated statements, return Result list."""
        return [self._execute(stmt) for stmt in parse(text)]

    def execute_statement(self, statement):
        """Execute an already-parsed statement (see storelens.parser)."""
        return self._execute(statement)

    def import_json(self, table_name, source):
        """Bulk-import a JSON file into an existing table.

        The file must contain a JSON array of objects; each object is one
        row keyed by column name. Missing keys become NULL, unknown keys
        and type mismatches raise StorelensError. Returns the number of
        imported rows.
        """
        table = self._get_table(table_name)
        if hasattr(source, "read"):
            data = json.load(source)
        else:
            with open(source, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        if not isinstance(data, list):
            raise StorelensError(
                "JSON import expects an array of objects, got %s"
                % type(data).__name__)
        count = 0
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                raise StorelensError(
                    "JSON import: element %d is %s, expected an object"
                    % (i, type(item).__name__))
            try:
                table.insert_row(item)
            except StorelensError as exc:
                raise StorelensError("JSON import row %d: %s" % (i, exc.message))
            count += 1
        return count

    # ---------- dispatch ----------

    def _execute(self, stmt):
        if isinstance(stmt, ast.CreateTable):
            return self._create_table(stmt)
        if isinstance(stmt, ast.DropTable):
            return self._drop_table(stmt)
        if isinstance(stmt, ast.Insert):
            return self._insert(stmt)
        if isinstance(stmt, ast.Update):
            return self._update(stmt)
        if isinstance(stmt, ast.Delete):
            return self._delete(stmt)
        if isinstance(stmt, ast.Select):
            return self._select(stmt)
        raise StorelensError("unsupported statement %r" % (stmt,))

    def _get_table(self, name):
        try:
            return self.tables[name]
        except KeyError:
            raise StorelensError("no such dataset (table): %s" % name)

    # ---------- DDL ----------

    def _create_table(self, stmt):
        if stmt.name in self.tables:
            raise StorelensError("dataset (table) %s already exists" % stmt.name)
        seen = set()
        columns = []
        for col_name, col_type, is_pk in stmt.columns:
            if col_name in seen:
                raise StorelensError(
                    "duplicate column name %s in CREATE TABLE" % col_name)
            seen.add(col_name)
            columns.append(Column(col_name, col_type, is_pk))
        self.tables[stmt.name] = Table(stmt.name, columns)
        return Result(message="table %s created" % stmt.name)

    def _drop_table(self, stmt):
        self._get_table(stmt.name)
        del self.tables[stmt.name]
        return Result(message="table %s dropped" % stmt.name)

    # ---------- DML ----------

    def _insert(self, stmt):
        table = self._get_table(stmt.table)
        if stmt.columns is None:
            target = table.column_names
        else:
            target = stmt.columns
            for name in target:
                table.get_column(name)  # validates existence
        for expr_row in stmt.rows:
            if len(expr_row) != len(target):
                raise StorelensError(
                    "INSERT into %s: %d values for %d columns"
                    % (table.name, len(expr_row), len(target)))
            values = {}
            for col_name, expr in zip(target, expr_row):
                _reject_non_constant(expr)
                values[col_name] = evaluate(expr, None, table)
            table.insert_row(values)
        return Result(message="%d row(s) inserted" % len(stmt.rows),
                      rowcount=len(stmt.rows))

    def _update(self, stmt):
        table = self._get_table(stmt.table)
        for col_name, _ in stmt.assignments:
            table.get_column(col_name)
        _validate_columns([expr for _, expr in stmt.assignments], table)
        if stmt.where is not None:
            _validate_columns([stmt.where], table)
        updated = 0
        for idx, row in enumerate(table.rows):
            if stmt.where is not None and not _matches(stmt.where, row, table):
                continue
            new_values = {}
            for col_name, expr in stmt.assignments:
                new_values[col_name] = evaluate(expr, row, table)
            candidate = dict(row)
            candidate.update(new_values)
            coerced = table.coerce_row(candidate)
            table.check_primary_key(coerced, ignore_index=idx)
            table.rows[idx] = coerced
            updated += 1
        return Result(message="%d row(s) updated" % updated, rowcount=updated)

    def _delete(self, stmt):
        table = self._get_table(stmt.table)
        if stmt.where is not None:
            _validate_columns([stmt.where], table)
        before = len(table.rows)
        if stmt.where is None:
            table.rows = []
        else:
            table.rows = [row for row in table.rows
                          if not _matches(stmt.where, row, table)]
        deleted = before - len(table.rows)
        return Result(message="%d row(s) deleted" % deleted, rowcount=deleted)

    # ---------- SELECT ----------

    def _select(self, stmt):
        table = self._get_table(stmt.table)
        # ORDER BY may reference output aliases; resolve them to the
        # underlying expression (a real column of the same name wins).
        aliases = {item.alias: item.expr for item in stmt.items
                   if item.alias is not None}
        resolved_order = []
        for expr, direction in stmt.order_by:
            if isinstance(expr, ast.Column) and not table.has_column(expr.name) \
                    and expr.name in aliases:
                expr = aliases[expr.name]
            resolved_order.append((expr, direction))
        stmt.order_by = resolved_order
        exprs = [item.expr for item in stmt.items
                 if not isinstance(item.expr, ast.Star)]
        if stmt.where is not None:
            exprs.append(stmt.where)
        exprs.extend(stmt.group_by)
        if stmt.having is not None:
            exprs.append(stmt.having)
        exprs.extend(expr for expr, _ in stmt.order_by)
        _validate_columns(exprs, table)

        rows = list(table.rows)
        if stmt.where is not None:
            rows = [row for row in rows if _matches(stmt.where, row, table)]

        grouped = bool(stmt.group_by) or \
            any(ast.contains_aggregate(item.expr) for item in stmt.items) or \
            (stmt.having is not None and ast.contains_aggregate(stmt.having))

        if grouped:
            pairs = self._project_grouped(stmt, table, rows)
        else:
            pairs = [self._project_row(stmt, table, row) for row in rows]

        if stmt.distinct:
            seen = set()
            unique = []
            for projected, keys in pairs:
                marker = _hashable(projected)
                if marker not in seen:
                    seen.add(marker)
                    unique.append((projected, keys))
            pairs = unique

        if stmt.order_by:
            pairs = self._sort(stmt, pairs)

        if stmt.offset:
            pairs = pairs[stmt.offset:]
        if stmt.limit is not None:
            pairs = pairs[:stmt.limit]

        return Result(columns=self._output_columns(stmt, table),
                      rows=[tuple(p) for p, _ in pairs])

    def _project_row(self, stmt, table, row):
        projected = []
        for item in stmt.items:
            if isinstance(item.expr, ast.Star):
                projected.extend(row[name] for name in table.column_names)
            else:
                projected.append(evaluate(item.expr, row, table))
        keys = [evaluate(expr, row, table) for expr, _ in stmt.order_by]
        return projected, keys

    def _project_grouped(self, stmt, table, rows):
        if stmt.group_by:
            groups = {}
            order = []
            for row in rows:
                key = _hashable(tuple(evaluate(g, row, table)
                                      for g in stmt.group_by))
                if key not in groups:
                    groups[key] = []
                    order.append(key)
                groups[key].append(row)
            group_list = [groups[key] for key in order]
        else:
            group_list = [rows]  # whole table is one group (may be empty)

        pairs = []
        for members in group_list:
            if members:
                representative = members[0]
            else:
                representative = {name: None for name in table.column_names}
            if stmt.having is not None:
                verdict = evaluate(stmt.having, representative, table, members)
                if verdict is None or not _truthy(verdict):
                    continue
            projected = []
            for item in stmt.items:
                if isinstance(item.expr, ast.Star):
                    projected.extend(representative[name]
                                     for name in table.column_names)
                else:
                    projected.append(
                        evaluate(item.expr, representative, table, members))
            keys = [evaluate(expr, representative, table, members)
                    for expr, _ in stmt.order_by]
            pairs.append((projected, keys))
        return pairs

    def _output_columns(self, stmt, table):
        names = []
        for item in stmt.items:
            if isinstance(item.expr, ast.Star):
                names.extend(table.column_names)
            elif item.alias is not None:
                names.append(item.alias)
            else:
                names.append(_default_column_name(item.expr))
        return names

    def _sort(self, stmt, pairs):
        directions = [direction for _, direction in stmt.order_by]

        def compare(left, right):
            for idx, direction in enumerate(directions):
                outcome = _compare_values(left[1][idx], right[1][idx])
                if outcome:
                    return outcome if direction == "ASC" else -outcome
            return 0

        return sorted(pairs, key=cmp_to_key(compare))


# ---------- helpers ----------

def _matches(expr, row, table):
    value = evaluate(expr, row, table)
    return value is not None and _truthy(value)


def _validate_columns(exprs, table):
    for expr in exprs:
        for node in _walk(expr):
            if isinstance(node, ast.Column) and not table.has_column(node.name):
                raise StorelensError(
                    "table %s has no column named %s"
                    % (table.name, node.name))
            if isinstance(node, ast.Star):
                # Star is only valid as COUNT(*) argument; FuncCall handles it
                pass


def _walk(expr):
    yield expr
    if isinstance(expr, ast.Unary):
        yield from _walk(expr.operand)
    elif isinstance(expr, ast.Binary):
        yield from _walk(expr.left)
        yield from _walk(expr.right)
    elif isinstance(expr, ast.IsNull):
        yield from _walk(expr.operand)
    elif isinstance(expr, ast.FuncCall):
        if not isinstance(expr.arg, ast.Star):
            yield from _walk(expr.arg)


def _reject_non_constant(expr):
    for node in _walk(expr):
        if isinstance(node, (ast.Column, ast.FuncCall, ast.Star)):
            raise StorelensError(
                "INSERT VALUES only accepts constant expressions")


def _default_column_name(expr):
    if isinstance(expr, ast.Column):
        return expr.name
    if isinstance(expr, ast.FuncCall):
        if isinstance(expr.arg, ast.Star):
            return "%s(*)" % expr.name
        if isinstance(expr.arg, ast.Column):
            return "%s(%s)" % (expr.name, expr.arg.name)
        return expr.name
    return "expr"


def _hashable(values):
    marker = []
    for value in values:
        marker.append((type(value).__name__, value))
    return tuple(marker)


def _compare_values(a, b):
    if a is None and b is None:
        return 0
    if a is None:
        return -1
    if b is None:
        return 1
    if is_number(a) and is_number(b):
        return (a > b) - (a < b)
    if isinstance(a, str) and isinstance(b, str):
        return (a > b) - (a < b)
    raise StorelensError("cannot order mixed values %r and %r" % (a, b))
