"""Recursive-descent parser for the storelens query language.

Grammar (informally):

    script      := statement (';' statement)* ';'? EOF   -- each statement
                    must be terminated by ';'
    statement   := create | drop | insert | update | delete | select
    create      := CREATE TABLE ident '(' coldef (',' coldef)* ')'
    coldef      := ident (INTEGER | REAL | TEXT) [PRIMARY KEY]
    drop        := DROP TABLE ident
    insert      := INSERT INTO ident ['(' ident (',' ident)* ')']
                   VALUES '(' expr (',' expr)* ')' (',' '(' ... ')')*
    update      := UPDATE ident SET ident '=' expr (',' ident '=' expr)*
                   [WHERE expr]
    delete      := DELETE FROM ident [WHERE expr]
    select      := SELECT [DISTINCT] item (',' item)* FROM ident
                   [WHERE expr] [GROUP BY expr (',' expr)*]
                   [HAVING expr]
                   [ORDER BY expr [ASC|DESC] (',' expr [ASC|DESC])*]
                   [LIMIT int [OFFSET int]]
    item        := '*' | expr [AS ident | ident]

Expression precedence (lowest to highest):
    OR -> AND -> NOT -> comparison (= != < <= > >=, IS [NOT] NULL)
    -> additive (+ -) -> multiplicative (* /) -> unary (-) -> primary
"""

from . import astnodes as ast
from .errors import StorelensError
from .lexer import tokenize

_TYPES = ("INTEGER", "REAL", "TEXT")
_COMPARISONS = ("=", "!=", "<", "<=", ">", ">=")


class Parser:
    def __init__(self, text):
        self.tokens = tokenize(text)
        self.pos = 0

    # ---------- token helpers ----------

    def peek(self, offset=0):
        idx = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[idx]

    def advance(self):
        tok = self.tokens[self.pos]
        if tok.type != "EOF":
            self.pos += 1
        return tok

    def error(self, message, tok=None):
        tok = tok or self.peek()
        raise StorelensError(message, tok.line, tok.col)

    def expect_punct(self, value):
        tok = self.peek()
        if tok.type == "PUNCT" and tok.value == value:
            return self.advance()
        self.error("expected %r but found %s" % (value, _describe(tok)))

    def expect_keyword(self, word):
        tok = self.peek()
        if tok.type == "KEYWORD" and tok.value == word:
            return self.advance()
        self.error("expected keyword %s but found %s" % (word, _describe(tok)))

    def accept_keyword(self, word):
        tok = self.peek()
        if tok.type == "KEYWORD" and tok.value == word:
            self.advance()
            return True
        return False

    def expect_ident(self):
        tok = self.peek()
        if tok.type == "IDENT":
            return self.advance().value
        self.error("expected an identifier but found %s" % _describe(tok))

    # ---------- entry point ----------

    def parse_script(self):
        statements = []
        while self.peek().type != "EOF":
            statements.append(self.parse_statement())
            self.expect_punct(";")
        return statements

    def parse_statement(self):
        tok = self.peek()
        if tok.type != "KEYWORD":
            self.error("expected a statement but found %s" % _describe(tok))
        kw = tok.value
        if kw == "CREATE":
            return self.parse_create()
        if kw == "DROP":
            return self.parse_drop()
        if kw == "INSERT":
            return self.parse_insert()
        if kw == "UPDATE":
            return self.parse_update()
        if kw == "DELETE":
            return self.parse_delete()
        if kw == "SELECT":
            return self.parse_select()
        self.error("unknown statement keyword %s" % kw, tok)

    # ---------- statements ----------

    def parse_create(self):
        self.expect_keyword("CREATE")
        self.expect_keyword("TABLE")
        name = self.expect_ident()
        self.expect_punct("(")
        columns = []
        while True:
            col_name = self.expect_ident()
            type_tok = self.peek()
            if type_tok.type == "KEYWORD" and type_tok.value in _TYPES:
                self.advance()
                col_type = type_tok.value
            else:
                self.error("expected a column type (INTEGER, REAL or TEXT) "
                           "but found %s" % _describe(type_tok))
            is_pk = False
            if self.accept_keyword("PRIMARY"):
                self.expect_keyword("KEY")
                is_pk = True
            columns.append((col_name, col_type, is_pk))
            if self.peek().type == "PUNCT" and self.peek().value == ",":
                self.advance()
                continue
            break
        self.expect_punct(")")
        return ast.CreateTable(name, columns)

    def parse_drop(self):
        self.expect_keyword("DROP")
        self.expect_keyword("TABLE")
        return ast.DropTable(self.expect_ident())

    def parse_insert(self):
        self.expect_keyword("INSERT")
        self.expect_keyword("INTO")
        table = self.expect_ident()
        columns = None
        if self.peek().type == "PUNCT" and self.peek().value == "(":
            self.advance()
            columns = [self.expect_ident()]
            while self.peek().type == "PUNCT" and self.peek().value == ",":
                self.advance()
                columns.append(self.expect_ident())
            self.expect_punct(")")
        self.expect_keyword("VALUES")
        rows = []
        while True:
            self.expect_punct("(")
            row = [self.parse_expr()]
            while self.peek().type == "PUNCT" and self.peek().value == ",":
                self.advance()
                row.append(self.parse_expr())
            self.expect_punct(")")
            rows.append(row)
            if self.peek().type == "PUNCT" and self.peek().value == ",":
                self.advance()
                continue
            break
        return ast.Insert(table, columns, rows)

    def parse_update(self):
        self.expect_keyword("UPDATE")
        table = self.expect_ident()
        self.expect_keyword("SET")
        assignments = []
        while True:
            col = self.expect_ident()
            tok = self.peek()
            if not (tok.type == "OP" and tok.value == "="):
                self.error("expected '=' in SET clause but found %s"
                           % _describe(tok))
            self.advance()
            assignments.append((col, self.parse_expr()))
            if self.peek().type == "PUNCT" and self.peek().value == ",":
                self.advance()
                continue
            break
        where = None
        if self.accept_keyword("WHERE"):
            where = self.parse_expr()
        return ast.Update(table, assignments, where)

    def parse_delete(self):
        self.expect_keyword("DELETE")
        self.expect_keyword("FROM")
        table = self.expect_ident()
        where = None
        if self.accept_keyword("WHERE"):
            where = self.parse_expr()
        return ast.Delete(table, where)

    def parse_select(self):
        self.expect_keyword("SELECT")
        distinct = self.accept_keyword("DISTINCT")
        items = []
        while True:
            items.append(self.parse_select_item())
            if self.peek().type == "PUNCT" and self.peek().value == ",":
                self.advance()
                continue
            break
        self.expect_keyword("FROM")
        table = self.expect_ident()
        where = None
        if self.accept_keyword("WHERE"):
            where = self.parse_expr()
        group_by = []
        if self.accept_keyword("GROUP"):
            self.expect_keyword("BY")
            group_by.append(self.parse_expr())
            while self.peek().type == "PUNCT" and self.peek().value == ",":
                self.advance()
                group_by.append(self.parse_expr())
        having = None
        if self.accept_keyword("HAVING"):
            having = self.parse_expr()
        order_by = []
        if self.accept_keyword("ORDER"):
            self.expect_keyword("BY")
            while True:
                expr = self.parse_expr()
                direction = "ASC"
                if self.accept_keyword("ASC"):
                    direction = "ASC"
                elif self.accept_keyword("DESC"):
                    direction = "DESC"
                order_by.append((expr, direction))
                if self.peek().type == "PUNCT" and self.peek().value == ",":
                    self.advance()
                    continue
                break
        limit = None
        offset = None
        if self.accept_keyword("LIMIT"):
            limit = self._non_negative_int("LIMIT")
            if self.accept_keyword("OFFSET"):
                offset = self._non_negative_int("OFFSET")
        elif self.accept_keyword("OFFSET"):
            offset = self._non_negative_int("OFFSET")
        return ast.Select(distinct, items, table, where, group_by, having,
                          order_by, limit, offset)

    def _non_negative_int(self, clause):
        tok = self.peek()
        if tok.type == "NUMBER" and isinstance(tok.value, int) \
                and not isinstance(tok.value, bool) and tok.value >= 0:
            self.advance()
            return tok.value
        self.error("%s expects a non-negative integer but found %s"
                   % (clause, _describe(tok)))

    def parse_select_item(self):
        tok = self.peek()
        if tok.type == "OP" and tok.value == "*":
            self.advance()
            return ast.SelectItem(ast.Star(), None)
        expr = self.parse_expr()
        alias = None
        if self.accept_keyword("AS"):
            alias = self.expect_ident()
        elif self.peek().type == "IDENT":
            alias = self.advance().value
        return ast.SelectItem(expr, alias)

    # ---------- expressions ----------

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.accept_keyword("OR"):
            left = ast.Binary("OR", left, self.parse_and())
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.accept_keyword("AND"):
            left = ast.Binary("AND", left, self.parse_not())
        return left

    def parse_not(self):
        if self.accept_keyword("NOT"):
            return ast.Unary("NOT", self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_additive()
        tok = self.peek()
        if tok.type == "OP" and tok.value in _COMPARISONS:
            self.advance()
            return ast.Binary(tok.value, left, self.parse_additive())
        if tok.type == "KEYWORD" and tok.value == "IS":
            self.advance()
            negated = self.accept_keyword("NOT")
            self.expect_keyword("NULL")
            return ast.IsNull(left, negated)
        return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while True:
            tok = self.peek()
            if tok.type == "OP" and tok.value in ("+", "-"):
                self.advance()
                left = ast.Binary(tok.value, left, self.parse_multiplicative())
            else:
                return left

    def parse_multiplicative(self):
        left = self.parse_unary()
        while True:
            tok = self.peek()
            if tok.type == "OP" and tok.value in ("*", "/"):
                self.advance()
                left = ast.Binary(tok.value, left, self.parse_unary())
            else:
                return left

    def parse_unary(self):
        tok = self.peek()
        if tok.type == "OP" and tok.value == "-":
            self.advance()
            return ast.Unary("-", self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        tok = self.peek()
        if tok.type == "NUMBER":
            self.advance()
            return ast.Literal(tok.value)
        if tok.type == "STRING":
            self.advance()
            return ast.Literal(tok.value)
        if tok.type == "KEYWORD" and tok.value == "NULL":
            self.advance()
            return ast.Literal(None)
        if tok.type == "KEYWORD" and tok.value in ast.AGGREGATES:
            self.advance()
            name = tok.value
            self.expect_punct("(")
            if self.peek().type == "OP" and self.peek().value == "*":
                self.advance()
                arg = ast.Star()
            else:
                arg = self.parse_expr()
            self.expect_punct(")")
            return ast.FuncCall(name, arg)
        if tok.type == "IDENT":
            self.advance()
            return ast.Column(tok.value)
        if tok.type == "PUNCT" and tok.value == "(":
            self.advance()
            expr = self.parse_expr()
            self.expect_punct(")")
            return expr
        self.error("unexpected %s in expression" % _describe(tok))


def _describe(tok):
    if tok.type == "EOF":
        return "end of input"
    if tok.type in ("KEYWORD", "IDENT"):
        return "%r" % tok.value
    if tok.type == "STRING":
        return "string %r" % tok.value
    if tok.type == "NUMBER":
        return "number %r" % tok.value
    return "%r" % tok.value


def parse(text):
    """Parse a script (one or more ';'-terminated statements)."""
    return Parser(text).parse_script()


def parse_one(text):
    """Parse a script that must contain exactly one statement."""
    statements = parse(text)
    if len(statements) != 1:
        raise StorelensError("expected exactly one statement, got %d"
                             % len(statements))
    return statements[0]
