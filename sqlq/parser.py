"""Recursive-descent parser turning token streams into AST nodes."""

from typing import List

from . import ast_nodes as ast
from .errors import SqlqError
from .lexer import tokenize, Token


COMPARISON_OPS = {"=", "==", "!=", "<>", "<", "<=", ">", ">="}
AGGREGATE_FUNCTIONS = {"COUNT", "SUM", "AVG", "MIN", "MAX"}
COLUMN_TYPES = {"INTEGER", "INT", "REAL", "TEXT"}


class Parser:
    def __init__(self, text):
        self.text = text
        self.tokens = tokenize(text)
        self.pos = 0

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------

    @property
    def current(self):
        return self.tokens[self.pos]

    def peek(self, offset=1):
        index = self.pos + offset
        if index < len(self.tokens):
            return self.tokens[index]
        return self.tokens[-1]

    def advance(self):
        token = self.tokens[self.pos]
        if token.kind != "EOF":
            self.pos += 1
        return token

    def is_keyword(self, word):
        token = self.current
        return token.kind == "KEYWORD" and token.value == word

    def is_punct(self, punct):
        token = self.current
        return token.kind == "PUNCT" and token.value == punct

    def accept_keyword(self, word):
        if self.is_keyword(word):
            return self.advance()
        return None

    def accept_punct(self, punct):
        if self.is_punct(punct):
            return self.advance()
        return None

    def expect_keyword(self, word):
        token = self.current
        if not (token.kind == "KEYWORD" and token.value == word):
            self.error("expected '{}' but found {}".format(
                word, self._describe(token)))
        return self.advance()

    def expect_punct(self, punct):
        token = self.current
        if token.kind != "PUNCT" or token.value != punct:
            self.error("expected '{}' but found {}".format(
                punct, self._describe(token)))
        return self.advance()

    def expect_identifier(self):
        token = self.current
        if token.kind != "IDENT":
            self.error("expected identifier but found {}".format(
                self._describe(token)))
        return self.advance().value

    def error(self, message, token=None):
        token = token or self.current
        raise SqlqError(message, token.line, token.column)

    @staticmethod
    def _describe(token):
        if token.kind == "EOF":
            return "end of input"
        return "'{}'".format(token.value)

    # ------------------------------------------------------------------
    # Top level
    # ------------------------------------------------------------------

    def parse_script(self):
        # type: () -> List[ast.Node]
        statements = []
        if self.current.kind == "EOF":
            self.error("no SQL statements to execute")
        while self.current.kind != "EOF":
            statements.append(self.parse_statement())
        return statements

    def parse_statement(self):
        token = self.current
        if token.kind != "KEYWORD":
            self.error("expected SQL statement but found {}".format(
                self._describe(token)))
        keyword = token.value
        if keyword == "CREATE":
            node = self.parse_create()
        elif keyword == "DROP":
            node = self.parse_drop()
        elif keyword == "INSERT":
            node = self.parse_insert()
        elif keyword == "UPDATE":
            node = self.parse_update()
        elif keyword == "DELETE":
            node = self.parse_delete()
        elif keyword == "SELECT":
            node = self.parse_select()
        else:
            self.error("unsupported SQL statement starting with '{}'".format(
                keyword))
        self.expect_punct(";")
        return node

    # ------------------------------------------------------------------
    # DDL
    # ------------------------------------------------------------------

    def parse_create(self):
        self.expect_keyword("CREATE")
        self.expect_keyword("TABLE")
        name = self.expect_identifier()
        self.expect_punct("(")
        columns = []
        primary_key = None
        seen = set()
        while True:
            column_name = self.expect_identifier()
            lower_name = column_name.lower()
            if lower_name in seen:
                self.error("duplicate column name '{}'".format(column_name))
            seen.add(lower_name)

            type_token = self.current
            if not (type_token.kind == "KEYWORD"
                    and type_token.value in COLUMN_TYPES):
                self.error("expected column type (INTEGER, REAL or TEXT) but "
                           "found {}".format(self._describe(type_token)))
            self.advance()
            column_type = "INTEGER" if type_token.value == "INT" \
                else type_token.value
            columns.append((column_name, column_type))

            if self.accept_keyword("PRIMARY"):
                self.expect_keyword("KEY")
                if primary_key is not None:
                    self.error("only one PRIMARY KEY column is allowed")
                primary_key = lower_name

            if self.accept_punct(","):
                continue
            break
        self.expect_punct(")")
        return ast.CreateTable(name=name, columns=columns,
                               primary_key=primary_key)

    def parse_drop(self):
        self.expect_keyword("DROP")
        self.expect_keyword("TABLE")
        name = self.expect_identifier()
        return ast.DropTable(name=name)

    # ------------------------------------------------------------------
    # DML
    # ------------------------------------------------------------------

    def parse_insert(self):
        self.expect_keyword("INSERT")
        self.expect_keyword("INTO")
        table = self.expect_identifier()
        columns = None
        if self.accept_punct("("):
            columns = []
            seen = set()
            while True:
                column_name = self.expect_identifier()
                if column_name.lower() in seen:
                    self.error("duplicate column '{}' in column list"
                               .format(column_name))
                seen.add(column_name.lower())
                columns.append(column_name)
                if self.accept_punct(","):
                    continue
                break
            self.expect_punct(")")
        self.expect_keyword("VALUES")
        self.expect_punct("(")
        values = [self.parse_expression()]
        while self.accept_punct(","):
            values.append(self.parse_expression())
        self.expect_punct(")")
        return ast.Insert(table=table, columns=columns, values=values)

    def parse_update(self):
        self.expect_keyword("UPDATE")
        table = self.expect_identifier()
        self.expect_keyword("SET")
        assignments = []
        while True:
            column_name = self.expect_identifier()
            qualifier = None
            if self.accept_punct("."):
                qualifier = column_name.lower()
                column_name = self.expect_identifier()
            self.expect_punct("=")
            value = self.parse_expression()
            assignments.append((column_name, value, qualifier))
            if self.accept_punct(","):
                continue
            break
        where = None
        if self.accept_keyword("WHERE"):
            where = self.parse_expression()
        return ast.Update(table=table, assignments=assignments, where=where)

    def parse_delete(self):
        self.expect_keyword("DELETE")
        self.expect_keyword("FROM")
        table = self.expect_identifier()
        where = None
        if self.accept_keyword("WHERE"):
            where = self.parse_expression()
        return ast.Delete(table=table, where=where)

    # ------------------------------------------------------------------
    # SELECT
    # ------------------------------------------------------------------

    def parse_select(self):
        self.expect_keyword("SELECT")
        distinct = self.accept_keyword("DISTINCT") is not None

        items = []
        if self.is_punct("*"):
            self.advance()
            items.append(ast.SelectItem(expr=ast.Star()))
        else:
            items.append(self.parse_select_item())
        while self.accept_punct(","):
            if self.is_punct("*"):
                self.error("'*' must be the only item in the select list")
            items.append(self.parse_select_item())

        table = None
        if self.accept_keyword("FROM"):
            table = self.expect_identifier()

        where = None
        if self.accept_keyword("WHERE"):
            where = self.parse_expression()

        group_by = []
        if self.accept_keyword("GROUP"):
            self.expect_keyword("BY")
            group_by.append(self.parse_expression())
            while self.accept_punct(","):
                group_by.append(self.parse_expression())

        having = None
        if self.accept_keyword("HAVING"):
            having = self.parse_expression()

        order_by = []
        if self.accept_keyword("ORDER"):
            self.expect_keyword("BY")
            order_by.append(self.parse_order_term())
            while self.accept_punct(","):
                order_by.append(self.parse_order_term())

        limit = None
        offset = 0
        if self.accept_keyword("LIMIT"):
            limit = self.parse_non_negative_int("LIMIT")
            if self.accept_keyword("OFFSET"):
                offset = self.parse_non_negative_int("OFFSET")
            elif self.accept_punct(","):
                # MySQL-style LIMIT offset, count
                offset = limit
                limit = self.parse_non_negative_int("LIMIT")
        elif self.accept_keyword("OFFSET"):
            offset = self.parse_non_negative_int("OFFSET")

        return ast.Select(items=items, table=table, where=where,
                          group_by=group_by, having=having, order_by=order_by,
                          distinct=distinct, limit=limit, offset=offset)

    def parse_select_item(self):
        expr = self.parse_expression()
        alias = None
        if self.accept_keyword("AS"):
            alias = self.expect_identifier()
        return ast.SelectItem(expr=expr, alias=alias)

    def parse_order_term(self):
        expr = self.parse_expression()
        descending = False
        if self.accept_keyword("ASC"):
            descending = False
        elif self.accept_keyword("DESC"):
            descending = True
        return ast.OrderTerm(expr=expr, descending=descending)

    def parse_non_negative_int(self, clause):
        token = self.current
        if token.kind != "NUMBER" or not isinstance(token.value, int) \
                or token.value < 0:
            self.error("{} expects a non-negative integer literal"
                       .format(clause))
        self.advance()
        return token.value

    # ------------------------------------------------------------------
    # Expressions (precedence climbing / recursive descent)
    # ------------------------------------------------------------------

    def parse_expression(self):
        return self.parse_or()

    def parse_or(self):
        node = self.parse_and()
        while self.is_keyword("OR"):
            self.advance()
            right = self.parse_and()
            node = ast.BinaryOp(op="OR", left=node, right=right)
        return node

    def parse_and(self):
        node = self.parse_not()
        while self.is_keyword("AND"):
            self.advance()
            right = self.parse_not()
            node = ast.BinaryOp(op="AND", left=node, right=right)
        return node

    def parse_not(self):
        if self.accept_keyword("NOT"):
            return ast.UnaryOp(op="NOT", operand=self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_additive()
        token = self.current
        if token.kind == "PUNCT" and token.value in COMPARISON_OPS:
            op = "!=" if token.value == "<>" else (
                "=" if token.value == "==" else token.value)
            self.advance()
            right = self.parse_additive()
            trailing = self.current
            if (trailing.kind == "PUNCT" and trailing.value in COMPARISON_OPS) \
                    or self.is_keyword("IS"):
                self.error("chained comparisons are not supported", trailing)
            return ast.BinaryOp(op=op, left=left, right=right)
        if self.accept_keyword("IS"):
            negated = self.accept_keyword("NOT") is not None
            self.expect_keyword("NULL")
            trailing = self.current
            if (trailing.kind == "PUNCT" and trailing.value in COMPARISON_OPS) \
                    or self.is_keyword("IS"):
                self.error("chained comparisons are not supported", trailing)
            return ast.IsNull(operand=left, negated=negated)
        return left

    def parse_additive(self):
        node = self.parse_multiplicative()
        while self.is_punct("+") or self.is_punct("-"):
            op = self.advance().value
            node = ast.BinaryOp(op=op, left=node,
                                right=self.parse_multiplicative())
        return node

    def parse_multiplicative(self):
        node = self.parse_unary()
        while self.is_punct("*") or self.is_punct("/"):
            op = self.advance().value
            node = ast.BinaryOp(op=op, left=node, right=self.parse_unary())
        return node

    def parse_unary(self):
        if self.is_punct("-") or self.is_punct("+"):
            op = self.advance().value
            return ast.UnaryOp(op=op, operand=self.parse_unary())
        if self.is_keyword("NOT"):
            return self.parse_not()
        return self.parse_primary()

    def parse_primary(self):
        token = self.current

        if token.kind == "PUNCT" and token.value == "(":
            self.advance()
            node = self.parse_expression()
            self.expect_punct(")")
            return node

        if token.kind == "NUMBER":
            self.advance()
            return ast.Literal(value=token.value)

        if token.kind == "STRING":
            self.advance()
            return ast.Literal(value=token.value)

        if token.kind == "KEYWORD" and token.value == "NULL":
            self.advance()
            return ast.Literal(value=None)

        if token.kind == "IDENT":
            name = self.advance().value
            upper = name.upper()

            if self.is_punct("("):
                if upper not in AGGREGATE_FUNCTIONS:
                    self.error("unknown function '{}'".format(name))
                return self.parse_aggregate(upper)

            if self.accept_punct("."):
                if self.is_punct("*"):
                    self.error("qualified '*' projections are not supported")
                column = self.expect_identifier()
                return ast.Column(name=column.lower(), table=name.lower())
            return ast.Column(name=name.lower())

        self.error("expected expression but found {}".format(
            self._describe(token)))

    def parse_aggregate(self, upper_name):
        self.expect_punct("(")
        distinct = self.accept_keyword("DISTINCT") is not None
        if self.is_punct("*"):
            if upper_name != "COUNT":
                self.error("'*' is only valid for COUNT")
            self.advance()
            self.expect_punct(")")
            return ast.Aggregate(name=upper_name, star=True, distinct=distinct)
        arg = self.parse_expression()
        self.expect_punct(")")
        return ast.Aggregate(name=upper_name, arg=arg, distinct=distinct)


def parse_statement(text):
    return Parser(text).parse_script()[0]


def parse_script(text):
    return Parser(text).parse_script()
