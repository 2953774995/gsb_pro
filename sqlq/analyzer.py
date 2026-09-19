"""Semantic analysis: name resolution and rule validation.

The analyzer walks a parsed statement against the current catalog and raises
:class:`SqlqError` for unknown tables/columns, invalid aggregate placement,
type misuse (SUM over TEXT) and malformed LIMIT clauses.

Analyzed SELECT statements receive extra bookkeeping attributes consumed by
the executor.
"""

from . import ast_nodes as ast
from .errors import SqlqError

AGGREGATES = frozenset(("COUNT", "SUM", "AVG", "MIN", "MAX"))


class _Scope:
    def __init__(self, table):
        self.table = table  # Table or None for table-less SELECT

    def resolve(self, ref):
        """Return the storage :class:`Column` for a ColumnRef node."""
        if self.table is None:
            raise SqlqError(
                f"column {ref.column!r} referenced but no FROM table was given"
            )
        if ref.table is not None and ref.table != self.table.name:
            raise SqlqError(
                f"unknown table {ref.table!r} (only {self.table.name!r} is in scope)"
            )
        column = self.table.column(ref.column)
        if column is None:
            raise SqlqError(
                f"unknown column {ref.column!r} in table {self.table.name!r}"
            )
        return column


# -- generic expression walkers --------------------------------------------

def walk(expr):
    """Yield an expression and every sub-expression (pre-order)."""
    yield expr
    if isinstance(expr, ast.UnaryOp):
        yield from walk(expr.operand)
    elif isinstance(expr, ast.BinaryOp):
        yield from walk(expr.left)
        yield from walk(expr.right)
    elif isinstance(expr, ast.IsNull):
        yield from walk(expr.operand)
    elif isinstance(expr, ast.FuncCall):
        if expr.arg is not None:
            yield from walk(expr.arg)


def collect_aggregates(expr):
    if expr is None:
        return []
    return [node for node in walk(expr) if isinstance(node, ast.FuncCall)]


def _assert_no_nested_aggregates(func):
    for node in walk(func.arg):
        if isinstance(node, ast.FuncCall) and node is not func:
            raise SqlqError(
                f"nested aggregate {node.name} inside {func.name} is not allowed"
            )


def _validate_aggregate(func, scope):
    if func.name not in AGGREGATES:
        raise SqlqError(f"unknown aggregate function {func.name!r}")
    if func.star:
        return
    for node in walk(func.arg):
        if isinstance(node, ast.FuncCall) and node is not func:
            raise SqlqError(
                f"nested aggregate {node.name} inside {func.name} is not allowed"
            )
    for node in walk(func.arg):
        if isinstance(node, ast.ColumnRef):
            column = scope.resolve(node)
            if func.name in ("SUM", "AVG") and column.data_type == "TEXT":
                raise SqlqError(
                    f"type mismatch: {func.name} cannot aggregate TEXT column {column.name!r}"
                )


def _validate_scalar_expr(expr, scope, allow_aggregate, clause_name):
    """Resolve columns and enforce aggregate placement rules."""
    aggregates = []
    for node in walk(expr):
        if isinstance(node, ast.FuncCall):
            aggregates.append(node)
            if not allow_aggregate:
                raise SqlqError(
                    f"aggregate {node.name}() is not allowed in {clause_name}"
                )
            _validate_aggregate(node, scope)
        elif isinstance(node, ast.ColumnRef):
            scope.resolve(node)
    return aggregates


def _is_constant_expr(expr):
    return not any(isinstance(n, (ast.ColumnRef, ast.FuncCall)) for n in walk(expr))


def _static_int(expr, what):
    if not _is_constant_expr(expr):
        raise SqlqError(f"{what} must be a constant integer expression")
    return expr  # executor evaluates with an empty row context


# -- statement entry point -------------------------------------------------

def analyze(statement, catalog):
    if isinstance(statement, ast.CreateTable):
        return statement
    if isinstance(statement, ast.DropTable):
        if statement.table not in catalog:
            raise SqlqError(f"unknown table {statement.table!r}")
        return statement
    if isinstance(statement, ast.Insert):
        return _analyze_insert(statement, catalog)
    if isinstance(statement, ast.Update):
        return _analyze_update(statement, catalog)
    if isinstance(statement, ast.Delete):
        return _analyze_delete(statement, catalog)
    if isinstance(statement, ast.Select):
        return _analyze_select(statement, catalog)
    raise SqlqError(f"unsupported statement type {type(statement).__name__}")


def _require_table(catalog, name):
    table = catalog.get(name)
    if table is None:
        raise SqlqError(f"unknown table {name!r}")
    return table


def _analyze_insert(statement, catalog):
    table = _require_table(catalog, statement.table)
    if statement.columns is None:
        target_columns = table.columns
        if len(statement.values) != len(target_columns):
            raise SqlqError(
                f"INSERT has {len(statement.values)} values but table "
                f"{table.name!r} has {len(target_columns)} columns"
            )
    else:
        seen = set()
        for name in statement.columns:
            if name in seen:
                raise SqlqError(f"duplicate column {name!r} in INSERT column list")
            seen.add(name)
            if table.column(name) is None:
                raise SqlqError(
                    f"unknown column {name!r} in table {table.name!r}"
                )
        if len(statement.values) != len(statement.columns):
            raise SqlqError(
                f"INSERT has {len(statement.values)} values but "
                f"{len(statement.columns)} columns"
            )
        target_columns = [table.column(n) for n in statement.columns]
    for value_expr, column in zip(statement.values, target_columns):
        for node in walk(value_expr):
            if isinstance(node, ast.FuncCall):
                raise SqlqError("aggregate/function calls are not allowed in INSERT VALUES")
            if isinstance(node, ast.ColumnRef):
                raise SqlqError("column references are not allowed in INSERT VALUES")
    return statement


def _analyze_update(statement, catalog):
    table = _require_table(catalog, statement.table)
    seen = set()
    for column_name, value_expr in statement.assignments:
        if column_name in seen:
            raise SqlqError(f"column {column_name!r} is assigned more than once")
        seen.add(column_name)
        if table.column(column_name) is None:
            raise SqlqError(
                f"unknown column {column_name!r} in table {table.name!r}"
            )
        for node in walk(value_expr):
            if isinstance(node, ast.FuncCall):
                raise SqlqError("aggregate calls are not allowed in UPDATE SET")
            if isinstance(node, ast.ColumnRef):
                _Scope(table).resolve(node)
    if statement.where is not None:
        _validate_scalar_expr(statement.where, _Scope(table), False, "WHERE clause")
    return statement


def _analyze_delete(statement, catalog):
    table = _require_table(catalog, statement.table)
    if statement.where is not None:
        _validate_scalar_expr(statement.where, _Scope(table), False, "WHERE clause")
    return statement


def _expand_items(statement, scope):
    """Expand * / table.* into concrete SelectItems.  Returns new item list."""
    expanded = []
    for item in statement.items:
        if isinstance(item, ast.Star):
            if scope.table is None:
                raise SqlqError("'*' requires a FROM clause")
            for column in scope.table.columns:
                ref = ast.ColumnRef(column.name, item.line, item.pos_col)
                expanded.append(ast.SelectItem(ref, None, item.line, item.pos_col))
        elif isinstance(item, ast.QualifiedStar):
            if scope.table is None or item.table != scope.table.name:
                raise SqlqError(
                    f"cannot expand {item.table!r}.*: table not in FROM clause"
                )
            for column in scope.table.columns:
                ref = ast.ColumnRef(column.name, item.line, item.pos_col,
                                    table=scope.table.name)
                expanded.append(ast.SelectItem(ref, None, item.line, item.pos_col))
        else:
            expanded.append(item)
    return expanded


def _column_key(expr):
    """Structural key of a simple column expression for GROUP BY matching."""
    if isinstance(expr, ast.ColumnRef):
        return (expr.table or "", expr.column)
    return None


def _analyze_select(statement, catalog):
    table = None
    if statement.table is not None:
        table = _require_table(catalog, statement.table)
    scope = _Scope(table)

    if table is None and statement.group_by is not None:
        raise SqlqError("GROUP BY requires a FROM clause")

    statement.items = _expand_items(statement, scope)

    # Validate output alias uniqueness and expressions.
    output_names = []
    seen_aliases = set()
    for item in statement.items:
        if item.alias is not None:
            if item.alias in seen_aliases:
                raise SqlqError(f"duplicate output column name {item.alias!r}")
            seen_aliases.add(item.alias)
        output_names.append(None)

    # WHERE: no aggregates, columns resolved.
    if statement.where is not None:
        _validate_scalar_expr(statement.where, scope, False, "WHERE clause")

    # GROUP BY: each expression may not contain aggregates; columns resolved.
    group_keys = set()
    if statement.group_by:
        for group_expr in statement.group_by:
            aggs = _validate_scalar_expr(group_expr, scope, False, "GROUP BY")
            if aggs:
                raise SqlqError("aggregate calls are not allowed in GROUP BY")
            key = _column_key(group_expr)
            if key is not None:
                group_keys.add(key)

    # HAVING allows aggregates.
    having_aggs = []
    if statement.having is not None:
        having_aggs = _validate_scalar_expr(
            statement.having, scope, True, "HAVING clause"
        )

    # SELECT items.  Aggregates collected first so grouping rules apply even
    # when the first aggregates appear in the projection list itself.
    item_aggregates = []
    for item in statement.items:
        item_aggregates.extend(
            _validate_scalar_expr(item.expr, scope, True, "SELECT list")
        )
    all_aggregates = list(item_aggregates)
    all_aggregates.extend(having_aggs)
    grouped = bool(statement.group_by) or bool(having_aggs) or bool(item_aggregates)
    for item in statement.items:
        if grouped:
            for node in walk(item.expr):
                if isinstance(node, ast.ColumnRef):
                    key = (node.table or "", node.column)
                    if key not in group_keys and not _inside_aggregate(node, item.expr):
                        if statement.group_by:
                            raise SqlqError(
                                f"column {node.column!r} must appear in GROUP BY "
                                f"or be used inside an aggregate"
                            )
                        raise SqlqError(
                            f"column {node.column!r} must appear in GROUP BY or "
                            f"be wrapped in an aggregate"
                        )

    # HAVING without GROUP BY: bare columns are not allowed (single group).
    if statement.having is not None and not statement.group_by:
        for node in walk(statement.having):
            if isinstance(node, ast.ColumnRef) and not _inside_aggregate(node, statement.having):
                raise SqlqError(
                    f"column {node.column!r} in HAVING must be used inside an aggregate "
                    f"without GROUP BY"
                )

    statement._grouped = grouped

    # ORDER BY: resolve output aliases and validate references.
    order_aggs = []
    if statement.order_by:
        alias_map = {}
        for idx, item in enumerate(statement.items):
            name = item.alias or output_label(item.expr)
            alias_map[name.lower()] = item.expr
        for key in statement.order_by:
            matched = None
            if isinstance(key.expr, ast.ColumnRef) and key.expr.table is None:
                matched = alias_map.get(key.expr.column.lower())
            if matched is not None:
                key.expr = matched
            order_aggs = _validate_scalar_expr(
                key.expr, scope, True, "ORDER BY"
            )
            if grouped:
                for node in walk(key.expr):
                    if isinstance(node, ast.ColumnRef):
                        col_key = (node.table or "", node.column)
                        if col_key not in group_keys and not _inside_aggregate(node, key.expr):
                            if statement.group_by:
                                raise SqlqError(
                                    f"ORDER BY column {node.column!r} must appear in "
                                    f"GROUP BY or the SELECT list"
                                )
            all_aggregates.extend(order_aggs)

    # Dedup aggregate nodes (same AST node may be reached from multiple
    # clauses only when shared; nodes are unique per syntactic occurrence).
    unique = {}
    for agg in all_aggregates:
        unique[id(agg)] = agg
    statement._aggregates = list(unique.values())

    # LIMIT / OFFSET: constant non-negative integers.
    if statement.limit is not None:
        _static_int(statement.limit, "LIMIT")
    if statement.offset is not None:
        _static_int(statement.offset, "OFFSET")

    return statement


def _inside_aggregate(target, root):
    for node in walk(root):
        if isinstance(node, ast.FuncCall):
            if node.arg is not None:
                for sub in walk(node.arg):
                    if sub is target:
                        return True
    return False


def output_label(expr):
    """Default result-column name for an expression without an alias."""
    if isinstance(expr, ast.ColumnRef):
        return expr.column
    if isinstance(expr, ast.FuncCall):
        if expr.star:
            return f"{expr.name}(*)"
        distinct = "DISTINCT " if expr.distinct else ""
        return f"{expr.name}({distinct}{output_label(expr.arg)})"
    if isinstance(expr, ast.Literal):
        if expr.value is None:
            return "NULL"
        if isinstance(expr.value, str):
            escaped = expr.value.replace("'", "''")
            return f"'{escaped}'"
        if isinstance(expr.value, bool):
            return "TRUE" if expr.value else "FALSE"
        return str(expr.value)
    if isinstance(expr, ast.UnaryOp):
        return f"{expr.op}{output_label(expr.operand)}"
    if isinstance(expr, ast.BinaryOp):
        return f"({output_label(expr.left)} {expr.op} {output_label(expr.right)})"
    if isinstance(expr, ast.IsNull):
        suffix = " IS NOT NULL" if expr.negated else " IS NULL"
        return f"{output_label(expr.operand)}{suffix}"
    return "expr"
