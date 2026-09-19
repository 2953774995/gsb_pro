"""In-memory execution engine for sqlq statements."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import ast_nodes as ast
from .errors import SqlqError
from .evaluator import (MISSING, EvalContext, evaluate, expr_to_sql, truthy,
                        type_name)
from .parser import parse_script


@dataclass
class ColumnSchema:
    name: str            # original, user-provided spelling
    type_name: str       # INTEGER / REAL / TEXT
    primary_key: bool = False


@dataclass
class Table:
    name: str            # original spelling
    columns: List[ColumnSchema]
    rows: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def column_names_lower(self):
        return [column.name.lower() for column in self.columns]

    def column_index(self, name_lower):
        names = self.column_names_lower
        if name_lower not in names:
            raise SqlqError("table '{}' has no column named '{}'".format(
                self.name, name_lower))
        return names.index(name_lower)

    def schema(self, name_lower):
        return self.columns[self.column_index(name_lower)]


@dataclass
class QueryResult:
    columns: List[str]
    rows: List[Tuple[Any, ...]]
    statement: str
    rowcount: int = -1   # affected-row count for DML, -1 when not applicable

    @property
    def tag(self):
        if self.statement == "SELECT":
            return "{} row(s)".format(len(self.rows))
        if self.statement == "INSERT":
            return "{} row(s) inserted".format(self.rowcount)
        if self.statement == "UPDATE":
            return "{} row(s) updated".format(self.rowcount)
        if self.statement == "DELETE":
            return "{} row(s) deleted".format(self.rowcount)
        return self.statement + " OK"


class _ConstantContext(EvalContext):
    def get_column(self, column):
        raise SqlqError("column references require a FROM clause")

    def get_aggregate(self, aggregate):
        raise SqlqError("aggregate functions require a FROM clause")


class RowContext(EvalContext):
    def __init__(self, table, row, columns_by_lower):
        self.table = table
        self.row = row
        self.columns_by_lower = columns_by_lower

    def get_column(self, column):
        if column.table is not None and column.table != self.table.lower():
            raise SqlqError("unknown table alias '{}'".format(column.table))
        if column.name not in self.columns_by_lower:
            raise SqlqError("unknown column '{}'".format(column.name))
        return self.row[column.name]

    def get_aggregate(self, aggregate):
        raise SqlqError("aggregate functions cannot be used here")


class GroupContext(EvalContext):
    def __init__(self, table, group_exprs, key_values, aggregate_values):
        self.table_name = table.lower()
        self.group_exprs = group_exprs
        self.key_values = key_values
        self.aggregate_values = aggregate_values

    def get_column(self, column):
        if column.table is not None and column.table != self.table_name:
            raise SqlqError("unknown table alias '{}'".format(column.table))
        for expr, value in zip(self.group_exprs, self.key_values):
            if isinstance(expr, ast.Column) and expr.name == column.name \
                    and (column.table is None or expr.table in (None, column.table)):
                return value
        return MISSING

    def get_aggregate(self, aggregate):
        for node, value in self.aggregate_values:
            if _same_aggregate(node, aggregate):
                return value
        raise SqlqError("aggregate expression not computed")


def _same_aggregate(a, b):
    if not (isinstance(a, ast.Aggregate) and isinstance(b, ast.Aggregate)):
        return False
    return a.name == b.name and a.star == b.star \
        and a.distinct == b.distinct and a.arg == b.arg


def _contains_aggregate(node):
    for child in _walk_exprs(node):
        if child is not node and isinstance(child, ast.Aggregate):
            return True
    return isinstance(node, ast.Aggregate)


def _walk_exprs(node):
    """Yield the node itself and every expression contained in it."""
    if node is None:
        return
    yield node
    if isinstance(node, ast.UnaryOp):
        for child in _walk_exprs(node.operand):
            yield child
    elif isinstance(node, ast.BinaryOp):
        for child in _walk_exprs(node.left):
            yield child
        for child in _walk_exprs(node.right):
            yield child
    elif isinstance(node, ast.IsNull):
        for child in _walk_exprs(node.operand):
            yield child
    elif isinstance(node, ast.Aggregate):
        if node.arg is not None:
            for child in _walk_exprs(node.arg):
                yield child


class Engine:
    """In-memory database. Tables live for the lifetime of the instance."""

    def __init__(self):
        self.tables = {}  # type: Dict[str, Table]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(self, sql):
        nodes = parse_script(sql)
        if len(nodes) != 1:
            raise SqlqError(
                "execute() expects exactly one statement ending with ';' "
                "(got {}); use execute_script() for multiple statements"
                .format(len(nodes)))
        return self._execute_node(nodes[0])

    def execute_script(self, sql_text):
        return [self._execute_node(node) for node in parse_script(sql_text)]

    # ------------------------------------------------------------------
    # Statement dispatch
    # ------------------------------------------------------------------

    def _execute_node(self, node):
        if isinstance(node, ast.CreateTable):
            return self._create_table(node)
        if isinstance(node, ast.DropTable):
            return self._drop_table(node)
        if isinstance(node, ast.Insert):
            return self._insert(node)
        if isinstance(node, ast.Update):
            return self._update(node)
        if isinstance(node, ast.Delete):
            return self._delete(node)
        if isinstance(node, ast.Select):
            return self._select(node)
        raise SqlqError("unsupported statement type {}".format(type(node)))

    # ------------------------------------------------------------------
    # DDL
    # ------------------------------------------------------------------

    def _create_table(self, node):
        key = node.name.lower()
        if key in self.tables:
            raise SqlqError("table '{}' already exists".format(node.name))
        if not node.columns:
            raise SqlqError("table '{}' must define at least one column"
                            .format(node.name))
        schemas = []
        for column_name, column_type in node.columns:
            schemas.append(ColumnSchema(
                name=column_name, type_name=column_type,
                primary_key=(node.primary_key == column_name.lower())))
        self.tables[key] = Table(name=node.name, columns=schemas)
        return QueryResult(columns=[], rows=[], statement="CREATE TABLE")

    def _drop_table(self, node):
        key = node.name.lower()
        if key not in self.tables:
            raise SqlqError("unknown table '{}'".format(node.name))
        del self.tables[key]
        return QueryResult(columns=[], rows=[], statement="DROP TABLE")

    def _get_table(self, name):
        table = self.tables.get(name.lower())
        if table is None:
            raise SqlqError("unknown table '{}'".format(name))
        return table

    # ------------------------------------------------------------------
    # Value coercion
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce(value, column):
        if value is None:
            return None
        if column.type_name == "INTEGER":
            if isinstance(value, bool) or not isinstance(value, int):
                raise SqlqError("column '{}' expects INTEGER but got {}"
                                .format(column.name, type_name(value)))
            return value
        if column.type_name == "REAL":
            if isinstance(value, bool) or not isinstance(value,
                                                         (int, float)):
                raise SqlqError("column '{}' expects REAL but got {}"
                                .format(column.name, type_name(value)))
            return float(value)
        if column.type_name == "TEXT":
            if not isinstance(value, str):
                raise SqlqError("column '{}' expects TEXT but got {}"
                                .format(column.name, type_name(value)))
            return value
        raise SqlqError("unknown column type '{}'".format(column.type_name))

    # ------------------------------------------------------------------
    # INSERT
    # ------------------------------------------------------------------

    def _insert(self, node):
        table = self._get_table(node.table)
        all_names = table.column_names_lower

        if node.columns is None:
            target_names = all_names
        else:
            target_names = []
            for column_name in node.columns:
                table.schema(column_name.lower())
                target_names.append(column_name.lower())

        if len(node.values) != len(target_names):
            raise SqlqError(
                "INSERT has {} value(s) but {} target column(s)".format(
                    len(node.values), len(target_names)))

        row = {name: None for name in all_names}
        for name, expr in zip(target_names, node.values):
            self._reject_columns(expr)
            value = evaluate(expr, _ConstantContext())
            row[name] = self._coerce(value, table.schema(name))

        for column in table.columns:
            if column.primary_key and row[column.name.lower()] is None:
                raise SqlqError(
                    "primary key column '{}' cannot be NULL"
                    .format(column.name))
            if column.primary_key:
                self._check_unique(table, column.name.lower(),
                                   row[column.name.lower()], None)

        table.rows.append(row)
        return QueryResult(columns=[], rows=[], statement="INSERT", rowcount=1)

    @staticmethod
    def _check_unique(table, name_lower, value, skip_index):
        for index, existing in enumerate(table.rows):
            if index != skip_index and existing[name_lower] == value \
                    and existing[name_lower] is not None:
                raise SqlqError(
                    "primary key violation: duplicate value {!r} in column "
                    "'{}'".format(value, table.schema(name_lower).name))

    @staticmethod
    def _reject_columns(expr):
        for child in _walk_exprs(expr):
            if isinstance(child, ast.Column):
                raise SqlqError("column references are not allowed here")

    # ------------------------------------------------------------------
    # UPDATE / DELETE
    # ------------------------------------------------------------------

    def _update(self, node):
        table = self._get_table(node.table)
        columns_by_lower = {column.name.lower(): column for column in
                            table.columns}

        assignment_targets = []
        for raw_name, expr, qualifier in node.assignments:
            name = raw_name.lower()
            if name not in columns_by_lower:
                raise SqlqError("unknown column '{}'".format(raw_name))
            if qualifier is not None and qualifier != node.table.lower():
                raise SqlqError("unknown table alias '{}'".format(qualifier))
            assignment_targets.append(name)
            self._validate_expr_refs(expr, table, allow_aggregate=False)
        if len(set(assignment_targets)) != len(assignment_targets):
            raise SqlqError("a column cannot be assigned more than once")

        if node.where is not None:
            self._validate_expr_refs(node.where, table, allow_aggregate=False)

        affected = 0
        for index, stored in enumerate(table.rows):
            context = RowContext(node.table, stored, columns_by_lower)
            if node.where is not None and \
                    not truthy(evaluate(node.where, context)):
                continue
            new_row = dict(stored)
            for name, expr, _qualifier in node.assignments:
                value = evaluate(expr, context)
                new_row[name] = self._coerce(value, columns_by_lower[name])

            for column in table.columns:
                name_lower = column.name.lower()
                if column.primary_key and new_row[name_lower] is None:
                    raise SqlqError(
                        "primary key column '{}' cannot be NULL"
                        .format(column.name))
                if column.primary_key and (
                        new_row[name_lower] != stored[name_lower]):
                    self._check_unique(table, name_lower,
                                       new_row[name_lower], index)
            table.rows[index] = new_row
            affected += 1

        return QueryResult(columns=[], rows=[], statement="UPDATE",
                           rowcount=affected)

    def _delete(self, node):
        table = self._get_table(node.table)
        columns_by_lower = {column.name.lower(): column for column in
                            table.columns}
        if node.where is not None:
            self._validate_expr_refs(node.where, table, allow_aggregate=False)
            kept = []
            affected = 0
            for stored in table.rows:
                context = RowContext(node.table, stored, columns_by_lower)
                if truthy(evaluate(node.where, context)):
                    affected += 1
                else:
                    kept.append(stored)
            table.rows = kept
        else:
            affected = len(table.rows)
            table.rows = []
        return QueryResult(columns=[], rows=[], statement="DELETE",
                           rowcount=affected)

    # ------------------------------------------------------------------
    # Semantic validation helpers
    # ------------------------------------------------------------------

    def _validate_expr_refs(self, expr, table, allow_aggregate):
        """Check column existence and (dis)allowed aggregate usage."""
        table_name_lower = table.name.lower()
        for child in _walk_exprs(expr):
            if isinstance(child, ast.Column):
                if child.table is not None and \
                        child.table != table_name_lower:
                    raise SqlqError("unknown table alias '{}'"
                                    .format(child.table))
                if child.name not in table.column_names_lower:
                    raise SqlqError("unknown column '{}'".format(child.name))
            elif isinstance(child, ast.Aggregate):
                if not allow_aggregate:
                    raise SqlqError(
                        "aggregate functions are not allowed in this clause")
                if child.star:
                    if child.arg is not None:
                        raise SqlqError("malformed COUNT(*)")
                else:
                    if _contains_aggregate(child.arg):
                        raise SqlqError("nested aggregate functions")
                    self._validate_expr_refs(child.arg, table,
                                             allow_aggregate=False)
                    self._check_aggregate_type(child, table)

    @staticmethod
    def _check_aggregate_type(aggregate, table):
        if aggregate.name not in ("SUM", "AVG"):
            return
        if aggregate.star or not isinstance(aggregate.arg, ast.Column):
            return
        if aggregate.arg.name in table.column_names_lower:
            column_type = table.schema(aggregate.arg.name).type_name
            if column_type == "TEXT":
                raise SqlqError(
                    "{} cannot be applied to TEXT column '{}'".format(
                        aggregate.name, aggregate.arg.name))

    # ------------------------------------------------------------------
    # SELECT
    # ------------------------------------------------------------------

    def _select(self, node):
        if node.table is None:
            return self._select_without_from(node)

        table = self._get_table(node.table)

        # A bare name in GROUP BY may refer to an output alias.
        real_columns = table.column_names_lower
        alias_map = {}
        for item in node.items:
            if item.alias is not None:
                alias_map[item.alias.lower()] = item.expr
        resolved_group_by = []
        for expr in node.group_by:
            if isinstance(expr, ast.Column) and expr.table is None \
                    and expr.name not in real_columns \
                    and expr.name in alias_map:
                expr = alias_map[expr.name]
            resolved_group_by.append(expr)
        node.group_by = resolved_group_by

        if node.where is not None:
            self._validate_expr_refs(node.where, table,
                                     allow_aggregate=False)
        for expr in node.group_by:
            self._validate_expr_refs(expr, table, allow_aggregate=False)

        has_star = any(isinstance(item.expr, ast.Star) for item in node.items)
        for item in node.items:
            if isinstance(item.expr, ast.Star):
                continue
            self._validate_expr_refs(item.expr, table, allow_aggregate=True)
        if node.having is not None:
            self._validate_expr_refs(node.having, table, allow_aggregate=True)

        aggregate_nodes = []
        for clause_expr in [item.expr for item in node.items
                            if not isinstance(item.expr, ast.Star)] + \
                ([node.having] if node.having is not None else []) + \
                [term.expr for term in node.order_by]:
            for child in _walk_exprs(clause_expr):
                if isinstance(child, ast.Aggregate) and not any(
                        _same_aggregate(child, other)
                        for other in aggregate_nodes):
                    aggregate_nodes.append(child)

        grouped = bool(node.group_by) or bool(aggregate_nodes)
        if has_star and grouped:
            raise SqlqError(
                "'*' cannot be combined with GROUP BY or aggregate functions")
        if node.having is not None and not grouped:
            raise SqlqError(
                "HAVING requires GROUP BY or an aggregate function")

        if grouped:
            for expr in node.group_by:
                if isinstance(expr, ast.Aggregate):
                    raise SqlqError("GROUP BY cannot contain aggregates")
            for item in node.items:
                if not isinstance(item.expr, ast.Star):
                    self._check_grouped_scope(item.expr, node.group_by)
            if node.having is not None:
                self._check_grouped_scope(node.having, node.group_by)

        columns_by_lower = {column.name.lower(): column for column in
                            table.columns}

        # WHERE filtering.
        filtered = []
        for stored in table.rows:
            context = RowContext(node.table, stored, columns_by_lower)
            if node.where is None or truthy(
                    evaluate(node.where, context)):
                filtered.append((stored, context))

        # Grouping / aggregate evaluation.
        if node.group_by:
            records = self._build_groups(table, node, filtered,
                                         aggregate_nodes)
        elif aggregate_nodes:
            records = self._build_single_aggregate_group(
                table, node.table, filtered, aggregate_nodes)
        else:
            records = [(context, None) for _, context in filtered]

        # HAVING.
        if node.having is not None:
            records = [
                pair for pair in records
                if truthy(_evaluate_grouped(node.having, pair[0]))]

        # Projection headers.
        headers = []
        for item in node.items:
            if isinstance(item.expr, ast.Star):
                headers.extend(column.name for column in table.columns)
            elif item.alias is not None:
                headers.append(item.alias)
            elif isinstance(item.expr, ast.Column):
                headers.append(table.schema(item.expr.name).name)
            else:
                headers.append(expr_to_sql(item.expr))
        if len(set(header.lower() for header in headers)) != len(headers):
            raise SqlqError("duplicate output column name in select list")

        # ORDER BY validation (ordinals and output aliases are resolved here).
        order_resolution = []
        for term in node.order_by:
            resolution = self._resolve_order_term(term, headers, table,
                                                  node.group_by, grouped)
            order_resolution.append((term, resolution))

        # Project.
        projected = []
        for context, _ in records:
            values = []
            for item in node.items:
                if isinstance(item.expr, ast.Star):
                    for column in table.columns:
                        values.append(context.row[column.name.lower()])
                else:
                    if grouped:
                        value = _evaluate_grouped(item.expr, context)
                    else:
                        value = evaluate(item.expr, context)
                    if value is MISSING:
                        raise SqlqError(
                            "expression is not part of GROUP BY nor an "
                            "aggregate")
                    values.append(value)
            projected.append((context, tuple(values)))

        # DISTINCT.
        if node.distinct:
            seen = set()
            unique = []
            for context, values in projected:
                if values not in seen:
                    seen.add(values)
                    unique.append((context, values))
            projected = unique

        # ORDER BY.
        if order_resolution:
            projected = self._order_rows(projected, order_resolution, headers,
                                     grouped)

        rows = [values for _, values in projected]

        # LIMIT / OFFSET.
        if node.offset:
            rows = rows[node.offset:]
        if node.limit is not None:
            rows = rows[:node.limit]

        return QueryResult(columns=headers, rows=rows, statement="SELECT")

    def _select_without_from(self, node):
        if node.where is not None or node.group_by or node.having is not None \
                or node.order_by:
            raise SqlqError("WHERE/GROUP BY/HAVING/ORDER BY require a FROM "
                            "clause")
        headers = []
        values = []
        context = _ConstantContext()
        for item in node.items:
            if isinstance(item.expr, ast.Star):
                raise SqlqError("'*' requires a FROM clause")
            self._reject_columns(item.expr)
            values.append(evaluate(item.expr, context))
            headers.append(item.alias if item.alias is not None
                           else expr_to_sql(item.expr))
        rows = [tuple(values)]
        if node.distinct:
            rows = list(set(rows))
        if node.limit is not None:
            rows = rows[:node.limit]
        return QueryResult(columns=headers, rows=rows, statement="SELECT")

    # ------------------------------------------------------------------
    # Grouping and aggregates
    # ------------------------------------------------------------------

    def _build_groups(self, table, node, filtered, aggregate_nodes):
        buckets = {}
        order_of_keys = []
        for stored, context in filtered:
            key = tuple(evaluate(expr, context) for expr in node.group_by)
            if key not in buckets:
                buckets[key] = []
                order_of_keys.append(key)
            buckets[key].append((stored, context))

        records = []
        for key in order_of_keys:
            rows_in_group = buckets[key]
            aggregate_values = [
                (agg, self._compute_aggregate(agg, rows_in_group))
                for agg in aggregate_nodes
            ]
            group_context = GroupContext(
                node.table, node.group_by, list(key), aggregate_values)
            records.append((group_context, rows_in_group))
        return records

    def _build_single_aggregate_group(self, table, table_name, filtered,
                                      aggregate_nodes):
        aggregate_values = [
            (agg, self._compute_aggregate(agg, filtered))
            for agg in aggregate_nodes
        ]
        context = GroupContext(table_name, [], [], aggregate_values)
        return [(context, filtered)]

    @staticmethod
    def _compute_aggregate(aggregate, rows_in_group):
        if aggregate.star:
            return len(rows_in_group)

        raw_values = [evaluate(aggregate.arg, context)
                      for _, context in rows_in_group]
        values = [value for value in raw_values if value is not None]

        if aggregate.distinct:
            unique = []
            seen = set()
            for value in values:
                if value not in seen:
                    seen.add(value)
                    unique.append(value)
            values = unique

        name = aggregate.name
        if name == "COUNT":
            return len(values)
        if not values:
            return None
        if name == "SUM":
            total = values[0]
            for value in values[1:]:
                total = _add_numeric(total, value)
            return total
        if name == "AVG":
            total = values[0]
            for value in values[1:]:
                total = _add_numeric(total, value)
            return total / len(values)
        if name in ("MIN", "MAX"):
            best = values[0]
            for value in values[1:]:
                if _compare_values(value, best) < 0:
                    best = value
            if name == "MIN":
                return best
            greatest = values[0]
            for value in values[1:]:
                if _compare_values(value, greatest) > 0:
                    greatest = value
            return greatest
        raise SqlqError("unknown aggregate '{}'".format(name))

    # ------------------------------------------------------------------
    # Grouped-query scope validation
    # ------------------------------------------------------------------

    @staticmethod
    def _check_grouped_scope(expr, group_exprs):
        """Every bare column must be a grouping column or inside an aggregate."""

        def walk(node, inside_aggregate):
            if isinstance(node, ast.Aggregate):
                if node.star:
                    return
                if _contains_aggregate(node.arg):
                    raise SqlqError("nested aggregate functions")
                walk(node.arg, True)
            elif isinstance(node, ast.Column):
                if inside_aggregate:
                    return
                allowed = any(
                    group_expr == node or
                    (not isinstance(group_expr, ast.Column)
                     and any(isinstance(child, ast.Column) and child == node
                             for child in _walk_exprs(group_expr)))
                    for group_expr in group_exprs)
                if not allowed:
                    raise SqlqError(
                        "column '{}' must appear in GROUP BY or be wrapped in "
                        "an aggregate".format(node.name))
            elif isinstance(node, ast.UnaryOp):
                walk(node.operand, inside_aggregate)
            elif isinstance(node, ast.BinaryOp):
                walk(node.left, inside_aggregate)
                walk(node.right, inside_aggregate)
            elif isinstance(node, ast.IsNull):
                walk(node.operand, inside_aggregate)

        walk(expr, isinstance(expr, ast.Aggregate))

    # ------------------------------------------------------------------
    # ORDER BY
    # ------------------------------------------------------------------

    def _resolve_order_term(self, term, headers, table, group_exprs, grouped):
        # ORDER BY <positive integer> refers to an output column position.
        if isinstance(term.expr, ast.Literal) and \
                isinstance(term.expr.value, int) and \
                not isinstance(term.expr.value, bool):
            position = term.expr.value
            if position < 1 or position > len(headers):
                raise SqlqError(
                    "ORDER BY position {} is out of range (select list has {} "
                    "column(s))".format(position, len(headers)))
            return ("ordinal", position - 1)

        # ORDER BY <output alias>.
        if isinstance(term.expr, ast.Column) and term.expr.table is None:
            lower = term.expr.name
            matches = [index for index, header in enumerate(headers)
                       if header.lower() == lower]
            if len(matches) == 1:
                return ("ordinal", matches[0])
            if len(matches) > 1:
                raise SqlqError("ambiguous ORDER BY name '{}'".format(lower))

        # Otherwise it is an ordinary expression against the source rows.
        self._validate_expr_refs(term.expr, table, allow_aggregate=grouped)
        if grouped:
            self._check_grouped_scope(term.expr, group_exprs)
        return ("expr", term.expr)

    @staticmethod
    def _order_rows(projected, order_resolution, headers, grouped):
        # Stable sort by each key, from the least significant to the most.
        result = list(projected)
        for term, resolution in reversed(order_resolution):
            result.sort(key=_make_sort_key(resolution, term.descending,
                                           grouped))
        return result


# ---------------------------------------------------------------------------
# Value comparison helpers
# ---------------------------------------------------------------------------


def _add_numeric(left, right):
    if isinstance(left, str) or isinstance(right, str):
        raise SqlqError("SUM/AVG cannot operate on TEXT values")
    if not isinstance(left, (int, float)) or isinstance(left, bool) \
            or not isinstance(right, (int, float)) or isinstance(right, bool):
        raise SqlqError("SUM/AVG requires numeric values")
    return left + right


def _compare_values(left, right):
    if isinstance(left, str) != isinstance(right, str) or \
            isinstance(left, (int, float)) != isinstance(right, (int, float)):
        raise SqlqError("cannot compare {} with {}".format(
            type_name(left), type_name(right)))
    if left < right:
        return -1
    if left > right:
        return 1
    return 0


class _SortKey:
    """Comparable wrapper implementing ASC/DESC plus NULLS FIRST/LAST."""

    __slots__ = ("value", "descending")

    def __init__(self, value, descending):
        self.value = value
        self.descending = descending

    def _fail(self, other):
        raise SqlqError("cannot compare {} with {} in ORDER BY".format(
            type_name(self.value), type_name(other.value)))

    def __lt__(self, other):
        left, right = self.value, other.value
        if isinstance(left, str) != isinstance(right, str) or \
                isinstance(left, (int, float)) != \
                isinstance(right, (int, float)):
            self._fail(other)
        result = left < right
        return (not result) if self.descending else result

    def __eq__(self, other):
        return self.value == other.value


def _substitute_group_keys(node, context):
    """Replace grouping-expression subtrees with literal key values."""
    for index, group_expr in enumerate(context.group_exprs):
        if node == group_expr:
            return ast.Literal(value=context.key_values[index])
    if isinstance(node, ast.Aggregate):
        return node
    if isinstance(node, ast.Literal):
        return node
    if isinstance(node, ast.Column):
        return node
    if isinstance(node, ast.UnaryOp):
        return ast.UnaryOp(op=node.op,
                           operand=_substitute_group_keys(node.operand,
                                                          context))
    if isinstance(node, ast.BinaryOp):
        return ast.BinaryOp(
            op=node.op,
            left=_substitute_group_keys(node.left, context),
            right=_substitute_group_keys(node.right, context))
    if isinstance(node, ast.IsNull):
        return ast.IsNull(
            operand=_substitute_group_keys(node.operand, context),
            negated=node.negated)
    return node


def _evaluate_grouped(node, context):
    return evaluate(_substitute_group_keys(node, context), context)


def _make_sort_key(resolution, descending, grouped):
    def key_pair(item):
        context, values = item
        if resolution[0] == "ordinal":
            value = values[resolution[1]]
        else:
            if grouped:
                value = _evaluate_grouped(resolution[1], context)
            else:
                value = evaluate(resolution[1], context)
            if value is MISSING:
                raise SqlqError(
                    "ORDER BY expression is not part of GROUP BY nor an "
                    "aggregate")
        # SQLite/MySQL convention: NULLs sort first under ASC, last DESC.
        null_rank = 0 if value is None else 1
        if descending:
            null_rank = 1 if value is None else 0
        return (null_rank, _SortKey(value, descending))

    return key_pair
