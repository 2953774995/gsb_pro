"""Recursive descent parser producing sqlq AST nodes."""

from . import ast_nodes as ast
from .errors import SqlqSyntaxError
from .lexer import (
    T_EOF, T_FLOAT, T_IDENT, T_INTEGER, T_KEYWORD, T_PUNCT, T_STAR, T_STRING,
    tokenize,
)

# Reserved words that have no grammar implementation yet.  Encountering them
# produces a clear error instead of a confusing "expected ..." message.
_UNSUPPORTED = frozenset(
    """
    ALTER BETWEEN CAST CROSS EXISTS FULL IN INTERSECT JOIN LEFT LIKE MINUS
    NATURAL RIGHT UNION WITH
    """.split()
)

_TERM_KEYWORDS = frozenset(
    {"FROM", "WHERE", "GROUP", "HAVING", "ORDER", "LIMIT", "OFFSET"}
)


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    # -- token helpers -----------------------------------------------------

    @property
    def tok(self):
        return self.tokens[self.pos]

    def peek(self, offset=1):
        index = self.pos + offset
        if index >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[index]

    def advance(self):
        current = self.tokens[self.pos]
        if current.kind != T_EOF:
            self.pos += 1
        return current

    def error(self, message, token=None):
        token = token or self.tok
        raise SqlqSyntaxError(message, token.line, token.column)

    def expect_punct(self, value):
        token = self.tok
        if token.kind not in (T_PUNCT, T_STAR) or token.value != value:
            self.error(f"expected {value!r} but found {self._describe(token)}")
        return self.advance()

    def expect_keyword(self, word):
        token = self.tok
        if not token.is_keyword(word):
            self.error(f"expected {word} but found {self._describe(token)}")
        return self.advance()

    def match_keyword(self, word):
        if self.tok.is_keyword(word):
            return self.advance()
        return None

    def match_punct(self, value):
        token = self.tok
        if token.kind in (T_PUNCT, T_STAR) and token.value == value:
            return self.advance()
        return None

    @staticmethod
    def _describe(token):
        if token.kind == T_EOF:
            return "end of input"
        if token.kind == T_KEYWORD:
            return f"keyword {token.value}"
        if token.kind in (T_INTEGER, T_FLOAT):
            return f"number {token.value}"
        if token.kind == T_STRING:
            return f"string {token.value!r}"
        if token.kind == T_STAR:
            return "'*'"
        return f"{token.value!r}"

    def check_unsupported(self):
        if self.tok.kind == T_KEYWORD and self.tok.value in _UNSUPPORTED:
            self.error(f"unsupported SQL feature: {self.tok.value}")

    # -- entry points ------------------------------------------------------

    def parse_statement(self):
        self.check_unsupported()
        token = self.tok
        if token.is_keyword("CREATE"):
            stmt = self.parse_create()
        elif token.is_keyword("DROP"):
            stmt = self.parse_drop()
        elif token.is_keyword("INSERT"):
            stmt = self.parse_insert()
        elif token.is_keyword("UPDATE"):
            stmt = self.parse_update()
        elif token.is_keyword("DELETE"):
            stmt = self.parse_delete()
        elif token.is_keyword("SELECT"):
            stmt = self.parse_select()
        elif token.kind == T_EOF:
            self.error("expected SQL statement but found end of input")
        else:
            self.error(f"unknown statement starting with {self._describe(token)}")
        terminator = self.tok
        if not terminator.is_punct(";"):
            self.error(f"expected ';' at end of statement but found {self._describe(terminator)}")
        self.advance()
        return stmt

    def parse_script(self):
        statements = []
        while self.tok.kind != T_EOF:
            statements.append(self.parse_statement())
        return statements

    # -- identifiers -------------------------------------------------------

    def parse_identifier(self, what="identifier"):
        token = self.tok
        if token.kind == T_IDENT:
            self.advance()
            return token.value
        self.error(f"expected {what} but found {self._describe(token)}")

    def parse_alias(self):
        if self.match_keyword("AS"):
            token = self.tok
            if token.kind != T_IDENT:
                self.error(f"expected alias name but found {self._describe(token)}")
            self.advance()
            return token.value
        # Bare alias: a non-reserved identifier that is not starting a clause.
        token = self.tok
        if token.kind == T_IDENT:
            self.advance()
            return token.value
        return None

    # -- DDL ---------------------------------------------------------------

    def parse_create(self):
        start = self.expect_keyword("CREATE")
        self.expect_keyword("TABLE")
        table = self.parse_identifier("table name")
        self.expect_punct("(")
        columns = []
        seen_names = set()
        while True:
            name_token = self.tok
            name = self.parse_identifier("column name")
            if name in seen_names:
                self.error(f"duplicate column name {name!r} in table definition", name_token)
            seen_names.add(name)
            type_token = self.tok
            if not type_token.is_keyword("INTEGER") and not type_token.is_keyword("REAL") \
                    and not type_token.is_keyword("TEXT"):
                self.error(
                    f"expected column type INTEGER, REAL or TEXT but found {self._describe(type_token)}"
                )
            data_type = self.advance().value
            primary_key = False
            not_null = False
            while True:
                if self.match_keyword("PRIMARY"):
                    self.expect_keyword("KEY")
                    primary_key = True
                    not_null = True
                elif self.match_keyword("NOT"):
                    self.expect_keyword("NULL")
                    not_null = True
                elif self.match_keyword("UNIQUE"):
                    self.error("UNIQUE constraint is not supported (use PRIMARY KEY)")
                elif self.tok.is_keyword("DEFAULT") or self.tok.is_keyword("REFERENCES") \
                        or self.tok.is_keyword("CHECK"):
                    self.error(f"unsupported column constraint: {self.tok.value}")
                else:
                    break
            columns.append(ast.ColumnDef(name, data_type, primary_key,
                                         name_token.line, name_token.column,
                                         not_null=not_null))
            if self.match_punct(","):
                continue
            break
        self.expect_punct(")")
        return ast.CreateTable(table, columns, start.line, start.column)

    def parse_drop(self):
        start = self.expect_keyword("DROP")
        self.expect_keyword("TABLE")
        if self.match_keyword("IF"):
            self.expect_keyword("EXISTS")
            self.error("DROP TABLE IF EXISTS is not supported")
        table = self.parse_identifier("table name")
        return ast.DropTable(table, start.line, start.column)

    # -- DML ---------------------------------------------------------------

    def parse_insert(self):
        start = self.expect_keyword("INSERT")
        self.expect_keyword("INTO")
        table = self.parse_identifier("table name")
        columns = None
        if self.match_punct("("):
            columns = []
            while True:
                columns.append(self.parse_identifier("column name"))
                if self.match_punct(","):
                    continue
                break
            self.expect_punct(")")
        self.expect_keyword("VALUES")
        values = []
        self.expect_punct("(")
        while True:
            values.append(self.parse_expression())
            if self.match_punct(","):
                continue
            break
        self.expect_punct(")")
        return ast.Insert(table, columns, values, start.line, start.column)

    def parse_update(self):
        start = self.expect_keyword("UPDATE")
        table = self.parse_identifier("table name")
        self.expect_keyword("SET")
        assignments = []
        while True:
            name_token = self.tok
            column = self.parse_identifier("column name")
            self.expect_punct("=")
            value = self.parse_expression()
            assignments.append((column, value))
            if self.match_punct(","):
                continue
            break
        where = None
        if self.match_keyword("WHERE"):
            where = self.parse_expression()
        return ast.Update(table, assignments, where, start.line, start.column)

    def parse_delete(self):
        start = self.expect_keyword("DELETE")
        self.expect_keyword("FROM")
        table = self.parse_identifier("table name")
        where = None
        if self.match_keyword("WHERE"):
            where = self.parse_expression()
        return ast.Delete(table, where, start.line, start.column)

    def parse_select(self):
        start = self.expect_keyword("SELECT")
        distinct = bool(self.match_keyword("DISTINCT"))
        self.match_keyword("ALL")  # explicit ALL == default behaviour

        items = []
        while True:
            item = self.parse_select_item()
            items.append(item)
            if self.match_punct(","):
                continue
            break

        table = None
        if self.match_keyword("FROM"):
            table = self.parse_identifier("table name")
            if self.tok.is_keyword("AS") or self.tok.kind == T_IDENT:
                # Reject aliases/JOINs: this engine is single-table only.
                if self.tok.is_keyword("AS") or (
                    self.tok.kind == T_IDENT
                    and self.peek().kind not in (T_PUNCT, T_STAR, T_KEYWORD)
                ):
                    self.advance()
                    alias_tok = self.tok
                    if alias_tok.kind == T_IDENT:
                        self.error("table aliases are not supported", alias_tok)
            if self.tok.is_keyword("JOIN") or self.tok.is_keyword("INNER") \
                    or self.tok.is_keyword("LEFT") or self.tok.is_keyword("RIGHT") \
                    or self.tok.is_keyword("FULL") or self.tok.is_keyword("CROSS") \
                    or self.tok.is_keyword("NATURAL") or self.tok.is_punct(","):
                self.error("JOIN queries are not supported by sqlq")

        where = None
        if self.match_keyword("WHERE"):
            where = self.parse_expression()

        group_by = None
        if self.match_keyword("GROUP"):
            self.expect_keyword("BY")
            group_by = []
            while True:
                group_by.append(self.parse_expression())
                if self.match_punct(","):
                    continue
                break

        having = None
        if self.match_keyword("HAVING"):
            having = self.parse_expression()

        order_by = None
        if self.match_keyword("ORDER"):
            self.expect_keyword("BY")
            order_by = []
            while True:
                key_token = self.tok
                key_expr = self.parse_expression()
                descending = False
                if self.match_keyword("ASC"):
                    descending = False
                elif self.match_keyword("DESC"):
                    descending = True
                order_by.append(ast.OrderKey(key_expr, descending,
                                             key_token.line, key_token.column))
                if self.match_punct(","):
                    continue
                break

        limit = None
        offset = None
        if self.match_keyword("LIMIT"):
            limit = self.parse_expression()
            if self.match_keyword("OFFSET"):
                offset = self.parse_expression()
        elif self.match_keyword("OFFSET"):
            self.error("OFFSET requires a LIMIT clause")
        return ast.Select(distinct, items, table, where, group_by, having,
                          order_by, limit, offset, start.line, start.column)

    def parse_select_item(self):
        token = self.tok
        if token.kind == T_STAR:
            self.advance()
            return ast.Star(token.line, token.column)
        if token.kind == T_IDENT and self.peek().is_punct("."):
            name = self.advance().value
            dot = self.advance()
            if self.tok.kind == T_STAR:
                star = self.advance()
                return ast.QualifiedStar(name, star.line, star.column)
            column_tok = self.tok
            column = self.parse_identifier("column name")
            expr = ast.ColumnRef(column, column_tok.line, column_tok.column,
                                 table=name)
            alias = self.parse_alias()
            return ast.SelectItem(expr, alias, token.line, token.column)
        expr = self.parse_expression()
        alias = self.parse_alias()
        return ast.SelectItem(expr, alias, token.line, token.column)

    # -- expressions -------------------------------------------------------

    def parse_expression(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.match_keyword("OR"):
            op_token = self.tokens[self.pos - 1]
            right = self.parse_and()
            left = ast.BinaryOp("OR", left, right, op_token.line, op_token.column)
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.match_keyword("AND"):
            op_token = self.tokens[self.pos - 1]
            right = self.parse_not()
            left = ast.BinaryOp("AND", left, right, op_token.line, op_token.column)
        return left

    def parse_not(self):
        if self.tok.is_keyword("NOT"):
            token = self.advance()
            return ast.UnaryOp("NOT", self.parse_not(), token.line, token.column)
        return self.parse_comparison()

    _COMPARISONS = ("=", "!=", "<>", "<", "<=", ">", ">=")

    def parse_comparison(self):
        left = self.parse_additive()
        while True:
            token = self.tok
            if token.kind in (T_PUNCT, T_STAR) and token.value in self._COMPARISONS:
                self.advance()
                op = "!=" if token.value == "<>" else token.value
                right = self.parse_additive()
                left = ast.BinaryOp(op, left, right, token.line, token.column)
                continue
            if self.match_keyword("IS"):
                negated = bool(self.match_keyword("NOT"))
                null_token = self.expect_keyword("NULL")
                left = ast.IsNull(left, negated, null_token.line, null_token.column)
                continue
            break
        return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while True:
            token = self.tok
            if token.is_punct("+") or token.is_punct("-"):
                self.advance()
                right = self.parse_multiplicative()
                left = ast.BinaryOp(token.value, left, right, token.line, token.column)
                continue
            break
        return left

    def parse_multiplicative(self):
        left = self.parse_unary()
        while True:
            token = self.tok
            if token.kind == T_STAR or (token.kind == T_PUNCT and token.value in ("/", "%")):
                self.advance()
                right = self.parse_unary()
                left = ast.BinaryOp("*", left, right, token.line, token.column) \
                    if token.kind == T_STAR else \
                    ast.BinaryOp(token.value, left, right, token.line, token.column)
                continue
            break
        return left

    def parse_unary(self):
        token = self.tok
        if token.is_punct("-") or token.is_punct("+"):
            self.advance()
            operand = self.parse_unary()
            return ast.UnaryOp(token.value, operand, token.line, token.column)
        return self.parse_primary()

    def parse_primary(self):
        self.check_unsupported()
        token = self.tok

        if token.kind == T_INTEGER or token.kind == T_FLOAT:
            self.advance()
            return ast.Literal(token.value, token.line, token.column)
        if token.kind == T_STRING:
            self.advance()
            return ast.Literal(token.value, token.line, token.column)
        if token.is_keyword("NULL"):
            self.advance()
            return ast.Literal(None, token.line, token.column)
        if token.is_keyword("TRUE"):
            self.advance()
            return ast.Literal(True, token.line, token.column)
        if token.is_keyword("FALSE"):
            self.advance()
            return ast.Literal(False, token.line, token.column)
        if token.is_punct("("):
            self.advance()
            expr = self.parse_expression()
            self.expect_punct(")")
            return expr
        if token.kind == T_IDENT:
            self.advance()
            if self.match_punct("("):
                return self.parse_function_call(token)
            if self.match_punct("."):
                column_tok = self.tok
                column = self.parse_identifier("column name")
                return ast.ColumnRef(column, column_tok.line, column_tok.column,
                                     table=token.value)
            return ast.ColumnRef(token.value, token.line, token.column)
        if token.kind == T_STAR:
            self.error("'*' is only valid in SELECT lists or COUNT(*)")
        if token.is_punct(";"):
            self.error("unexpected end of expression (found ';')")
        self.error(f"unexpected token in expression: {self._describe(token)}")

    def parse_function_call(self, name_token):
        name = name_token.value.upper()
        distinct = bool(self.match_keyword("DISTINCT"))
        if self.tok.kind == T_STAR:
            star_token = self.advance()
            self.expect_punct(")")
            if name != "COUNT":
                self.error(f"only COUNT(*) is supported, not {name}(*)", name_token)
            if distinct:
                self.error("COUNT(DISTINCT *) is not valid SQL", name_token)
            return ast.FuncCall(name, name_token.line, name_token.column,
                                arg=None, star=True)
        arg = self.parse_expression()
        self.expect_punct(")")
        if name not in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
            self.error(f"unknown function {name_token.value!r}", name_token)
        return ast.FuncCall(name, name_token.line, name_token.column,
                            arg=arg, distinct=distinct)


def parse(sql):
    """Parse a single trailing-semicolon-terminated statement."""
    return Parser(tokenize(sql)).parse_statement()


def parse_script(sql_text):
    """Parse zero or many semicolon-terminated statements."""
    return Parser(tokenize(sql_text)).parse_script()


def parse_expression(sql):
    """Parse a standalone expression (no trailing semicolon required)."""
    parser = Parser(tokenize(sql))
    expr = parser.parse_expression()
    if parser.tok.kind != T_EOF:
        parser.error(f"unexpected trailing input: {parser._describe(parser.tok)}")
    return expr
