"""Recursive-descent parser for the storelens query language.

Grammar (EBNF-ish)::

    script      := statement (';' statement)* ';'?
    statement   := create | drop | insert | update | delete | select
    create      := CREATE TABLE ident '(' column_def (',' column_def)* ')'
    column_def  := ident (INTEGER | REAL | TEXT) [PRIMARY KEY]
    drop        := DROP TABLE ident
    insert      := INSERT INTO ident ['(' ident (',' ident)* ')']
                   VALUES '(' expr_list ')' (',' '(' expr_list ')')*
    update      := UPDATE ident SET ident '=' expr (',' ident '=' expr)*
                   [WHERE expr]
    delete      := DELETE FROM ident [WHERE expr]
    select      := SELECT [DISTINCT] select_item (',' select_item)*
                   FROM ident
                   [WHERE expr]
                   [GROUP BY expr (',' expr)*]
                   [HAVING expr]
                   [ORDER BY expr [ASC|DESC] (',' expr [ASC|DESC])*]
                   [LIMIT integer [OFFSET integer]]
    select_item := expr [AS ident] | '*'
    expr        := or_expr
    or_expr     := and_expr (OR and_expr)*
    and_expr    := not_expr (AND not_expr)*
    not_expr    := NOT not_expr | comparison
    comparison  := additive ((=|!=|<>|<|<=|>|>=) additive
                   | IS [NOT] NULL)?
    additive    := multiplicative ((+|-) multiplicative)*
    multiplicative := unary ((*|/|%) unary)*
    unary       := (-|+) unary | primary
    primary     := number | string | NULL | ident | funcall | '(' expr ')' | '*'
"""

from .errors import StorelensError
from .lexer import (tokenize, KEYWORD, IDENT, STRING, NUMBER, OP, PUNCT, EOF)
from . import ast_nodes as ast

AGGREGATE_FUNCTIONS = {"COUNT", "SUM", "AVG", "MIN", "MAX"}


class Parser:
    def __init__(self, text):
        self.tokens = tokenize(text)
        self.pos = 0

    # -- token helpers ----------------------------------------------------

    def peek(self, ahead=0):
        idx = min(self.pos + ahead, len(self.tokens) - 1)
        return self.tokens[idx]

    def next(self):
        tok = self.tokens[self.pos]
        if tok.type != EOF:
            self.pos += 1
        return tok

    def error(self, msg, tok=None):
        tok = tok or self.peek()
        raise StorelensError(
            "Syntax error at line %d, column %d: %s" % (tok.line, tok.col, msg))

    def at_keyword(self, *words):
        tok = self.peek()
        return tok.type == KEYWORD and tok.value in words

    def expect_keyword(self, word):
        if not self.at_keyword(word):
            self.error("expected keyword %s but found %s"
                       % (word, self._describe(self.peek())))
        return self.next()

    def accept_keyword(self, word):
        if self.at_keyword(word):
            return self.next()
        return None

    def expect_punct(self, ch):
        tok = self.peek()
        if tok.type != PUNCT or tok.value != ch:
            self.error("expected %r but found %s"
                       % (ch, self._describe(tok)))
        return self.next()

    def accept_punct(self, ch):
        tok = self.peek()
        if tok.type == PUNCT and tok.value == ch:
            return self.next()
        return None

    def expect_ident(self):
        tok = self.peek()
        if tok.type != IDENT:
            self.error("expected identifier but found %s"
                       % self._describe(tok))
        return self.next().value

    @staticmethod
    def _describe(tok):
        if tok.type == EOF:
            return "end of input"
        return "%r" % tok.value

    # -- entry points ------------------------------------------------------

    def parse_script(self):
        """Parse one or more semicolon-terminated statements."""
        statements = []
        while self.peek().type != EOF:
            if self.accept_punct(";"):
                continue  # tolerate stray semicolons / empty statements
            statements.append(self.parse_statement())
            self.expect_punct(";")
        if not statements:
            self.error("empty statement", self.peek())
        return statements

    def parse_statement(self):
        tok = self.peek()
        if tok.type == IDENT:
            self.error("unknown statement keyword %r" % tok.value)
        if tok.type != KEYWORD:
            self.error("expected a statement but found %s"
                       % self._describe(tok))
        word = tok.value
        if word == "CREATE":
            return self.parse_create()
        if word == "DROP":
            return self.parse_drop()
        if word == "INSERT":
            return self.parse_insert()
        if word == "UPDATE":
            return self.parse_update()
        if word == "DELETE":
            return self.parse_delete()
        if word == "SELECT":
            return self.parse_select()
        self.error("unknown statement keyword %r" % word)

    # -- statements ---------------------------------------------------------

    def parse_create(self):
        self.expect_keyword("CREATE")
        self.expect_keyword("TABLE")
        name = self.expect_ident()
        self.expect_punct("(")
        columns = []
        seen_pk = False
        while True:
            col_name = self.expect_ident()
            tok = self.peek()
            if tok.type != KEYWORD or tok.value not in ("INTEGER", "REAL", "TEXT"):
                self.error("expected column type INTEGER, REAL or TEXT but "
                           "found %s" % self._describe(tok))
            type_name = self.next().value
            primary_key = False
            if self.accept_keyword("PRIMARY"):
                self.expect_keyword("KEY")
                if seen_pk:
                    self.error("only one PRIMARY KEY column is allowed")
                primary_key = True
                seen_pk = True
            columns.append(ast.ColumnDef(col_name, type_name, primary_key))
            if not self.accept_punct(","):
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
        if self.accept_punct("("):
            columns = [self.expect_ident()]
            while self.accept_punct(","):
                columns.append(self.expect_ident())
            self.expect_punct(")")
        self.expect_keyword("VALUES")
        rows = []
        while True:
            self.expect_punct("(")
            values = [self.parse_expr()]
            while self.accept_punct(","):
                values.append(self.parse_expr())
            self.expect_punct(")")
            rows.append(values)
            if not self.accept_punct(","):
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
            if tok.type != OP or tok.value != "=":
                self.error("expected '=' in SET clause but found %s"
                           % self._describe(tok))
            self.next()
            assignments.append((col, self.parse_expr()))
            if not self.accept_punct(","):
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
        distinct = bool(self.accept_keyword("DISTINCT"))
        items = []
        while True:
            tok = self.peek()
            if tok.type == OP and tok.value == "*":
                self.next()
                items.append(ast.SelectItem(ast.Star()))
            else:
                expr = self.parse_expr()
                alias = None
                if self.accept_keyword("AS"):
                    alias = self.expect_ident()
                elif self.peek().type == IDENT:
                    alias = self.next().value
                items.append(ast.SelectItem(expr, alias))
            if not self.accept_punct(","):
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
            while self.accept_punct(","):
                group_by.append(self.parse_expr())
        having = None
        if self.accept_keyword("HAVING"):
            having = self.parse_expr()
        order_by = []
        if self.accept_keyword("ORDER"):
            self.expect_keyword("BY")
            while True:
                expr = self.parse_expr()
                descending = False
                if self.accept_keyword("DESC"):
                    descending = True
                else:
                    self.accept_keyword("ASC")
                order_by.append(ast.OrderItem(expr, descending))
                if not self.accept_punct(","):
                    break
        limit = None
        offset = None
        if self.accept_keyword("LIMIT"):
            limit = self._parse_non_negative_int("LIMIT")
            if self.accept_keyword("OFFSET"):
                offset = self._parse_non_negative_int("OFFSET")
        elif self.at_keyword("OFFSET"):
            self.next()
            offset = self._parse_non_negative_int("OFFSET")
        return ast.Select(distinct, items, table, where, group_by,
                          having, order_by, limit, offset)

    def _parse_non_negative_int(self, clause):
        tok = self.peek()
        if tok.type != NUMBER or not isinstance(tok.value, int) or tok.value < 0:
            self.error("%s requires a non-negative integer but found %s"
                       % (clause, self._describe(tok)))
        self.next()
        return tok.value

    # -- expressions (precedence climbing) ---------------------------------

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.at_keyword("OR"):
            self.next()
            left = ast.BinaryOp("OR", left, self.parse_and())
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.at_keyword("AND"):
            self.next()
            left = ast.BinaryOp("AND", left, self.parse_not())
        return left

    def parse_not(self):
        if self.at_keyword("NOT"):
            self.next()
            return ast.UnaryOp("NOT", self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_additive()
        tok = self.peek()
        if tok.type == OP and tok.value in ("=", "!=", "<>", "<", "<=", ">", ">="):
            self.next()
            op = "!=" if tok.value == "<>" else tok.value
            return ast.BinaryOp(op, left, self.parse_additive())
        if self.at_keyword("IS"):
            self.next()
            negated = bool(self.accept_keyword("NOT"))
            self.expect_keyword("NULL")
            return ast.IsNull(left, negated)
        return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while True:
            tok = self.peek()
            if tok.type == OP and tok.value in ("+", "-"):
                self.next()
                left = ast.BinaryOp(tok.value, left,
                                    self.parse_multiplicative())
            else:
                return left

    def parse_multiplicative(self):
        left = self.parse_unary()
        while True:
            tok = self.peek()
            if tok.type == OP and tok.value in ("*", "/", "%"):
                self.next()
                left = ast.BinaryOp(tok.value, left, self.parse_unary())
            else:
                return left

    def parse_unary(self):
        tok = self.peek()
        if tok.type == OP and tok.value in ("-", "+"):
            self.next()
            return ast.UnaryOp(tok.value, self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        tok = self.peek()
        if tok.type == NUMBER:
            self.next()
            return ast.Literal(tok.value)
        if tok.type == STRING:
            self.next()
            return ast.Literal(tok.value)
        if tok.type == KEYWORD and tok.value == "NULL":
            self.next()
            return ast.Literal(None)
        if tok.type == IDENT:
            self.next()
            name = tok.value
            if self.accept_punct("("):
                # Function call (aggregate)
                star_tok = self.peek()
                if star_tok.type == OP and star_tok.value == "*":
                    self.next()
                    self.expect_punct(")")
                    return ast.FuncCall(name, [], star=True)
                args = [self.parse_expr()]
                while self.accept_punct(","):
                    args.append(self.parse_expr())
                self.expect_punct(")")
                return ast.FuncCall(name, args)
            return ast.Column(name)
        if tok.type == PUNCT and tok.value == "(":
            self.next()
            expr = self.parse_expr()
            self.expect_punct(")")
            return expr
        self.error("expected an expression but found %s"
                   % self._describe(tok))


def parse(text):
    """Parse a single statement; the text must contain exactly one."""
    statements = parse_script(text)
    if len(statements) != 1:
        raise StorelensError(
            "expected exactly one statement, got %d" % len(statements))
    return statements[0]


def parse_script(text):
    """Parse a script of one or more statements."""
    return Parser(text).parse_script()
