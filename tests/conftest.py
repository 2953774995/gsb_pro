"""Shared pytest helpers.

The SQL grammar requires a trailing semicolon.  A tiny ``TestEngine`` wrapper
adds it automatically so individual test queries read like normal SQL strings.
"""

import pytest

from sqlq import Engine as _Engine


class TestEngine(_Engine):
    @staticmethod
    def _with_semicolon(sql):
        stripped = sql.rstrip()
        if not stripped.endswith(";"):
            return stripped + ";"
        return sql

    def execute(self, sql):
        return super().execute(self._with_semicolon(sql))

    def execute_script(self, sql_text):
        return super().execute_script(sql_text)


@pytest.fixture()
def engine():
    return TestEngine()
