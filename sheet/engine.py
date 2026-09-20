"""Formula dependency graph and incremental recalculation."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Iterable

from .formula import (
    Evaluator,
    FormulaSyntaxError,
    Node,
    node_references,
    parse_formula,
)
from .model import (
    CellAddress,
    CellError,
    CycleErrorValue,
    ParseErrorValue,
    Sheet,
    parse_number,
)

__all__ = ["FormulaError", "SpreadsheetEngine"]


class FormulaError(Exception):
    """User-facing formula editing error (also stored as #PARSE! when needed)."""


class SpreadsheetEngine:
    def __init__(self, sheet: Sheet | None = None) -> None:
        self.sheet = sheet or Sheet()
        self.ast: dict[CellAddress, Node] = {}
        self.values: dict[CellAddress, object] = {}
        # Explicit dependencies for each formula.
        self.dependencies: dict[CellAddress, set[CellAddress]] = defaultdict(set)
        # Reverse map: input cell -> formulas directly depending on it.
        self.dependents: dict[CellAddress, set[CellAddress]] = defaultdict(set)
        self._rebuild_all()

    # ------------------------------- editing -------------------------------
    def set_cell(self, addr: CellAddress, content: str) -> None:
        """Set raw content and incrementally recalculate dependents."""
        content = "" if content is None else str(content)
        old_formula = addr in self.ast
        new_formula = content.startswith("=")

        # Remove the outgoing edges before attempting a parse. Other formulas
        # that depend on addr are recomputed below and will see its new value.
        if old_formula:
            self._remove_formula_edges(addr)
            self.ast.pop(addr, None)

        self.sheet.set_content(addr, content)

        if new_formula:
            try:
                tree = parse_formula(content)
            except FormulaSyntaxError as exc:
                self.values[addr] = ParseErrorValue(str(exc))
                # Old incoming dependents remain: this is a value-producing cell,
                # albeit an error. If it had no parseable refs, none are added.
                self._recompute_from({addr})
                return FormulaError(str(exc))
            self.ast[addr] = tree
            refs = node_references(tree)
            deps = self._expand_refs(refs)
            self.dependencies[addr] = deps
            for dep in deps:
                self.dependents[dep].add(addr)
            roots = {addr}
        else:
            roots = {addr}

        self._recompute_from(roots)
        return None

    def clear_cell(self, addr: CellAddress) -> None:
        if addr in self.ast:
            self._remove_formula_edges(addr)
            self.ast.pop(addr, None)
        self.sheet.clear(addr)
        self.values.pop(addr, None)
        self._recompute_from({addr})

    def load_sheet(self, sheet: Sheet) -> None:
        self.sheet = sheet
        self.ast.clear()
        self.values.clear()
        self.dependencies.clear()
        self.dependents.clear()
        self._rebuild_all()

    def _rebuild_all(self) -> None:
        """Parse all formulas and run a global topological calculation."""
        self.ast.clear()
        self.values.clear()
        self.dependencies.clear()
        self.dependents.clear()

        for addr, content in list(self.sheet.cells.items()):
            if content.startswith("="):
                try:
                    tree = parse_formula(content)
                except FormulaSyntaxError as exc:
                    self.values[addr] = ParseErrorValue(str(exc))
                    continue
                self.ast[addr] = tree
                refs = self._expand_refs(node_references(tree))
                self.dependencies[addr] = refs
                for ref in refs:
                    self.dependents[ref].add(addr)

        formulas = set(self.ast)
        indegree: dict[CellAddress, int] = {f: 0 for f in formulas}
        for formula, deps in self.dependencies.items():
            if formula in formulas:
                indegree[formula] = len(deps & formulas)
        queue = deque(f for f, degree in indegree.items() if degree == 0)
        seen: set[CellAddress] = set()
        while queue:
            formula = queue.popleft()
            seen.add(formula)
            self.values[formula] = self._evaluate(formula)
            for dependent in self.dependents.get(formula, ()):  # type: ignore[arg-type]
                if dependent in indegree:
                    indegree[dependent] -= 1
                    if indegree[dependent] == 0:
                        queue.append(dependent)

        cyclic = formulas - seen
        for addr in self._formula_closure(cyclic):
            self.values[addr] = CycleErrorValue("circular reference")

    # ---------------------------- dependency core --------------------------
    def _remove_formula_edges(self, formula: CellAddress) -> None:
        for dep in self.dependencies.pop(formula, set()):
            users = self.dependents.get(dep)
            if users is not None:
                users.discard(formula)
                if not users:
                    self.dependents.pop(dep, None)

    @staticmethod
    def _expand_refs(
        refs: Iterable[tuple[CellAddress, CellAddress | None]],
    ) -> set[CellAddress]:
        result: set[CellAddress] = set()
        for start, end in refs:
            if end is None:
                result.add(start)
            else:
                for row in range(start.row, end.row + 1):
                    for col in range(start.col, end.col + 1):
                        result.add(CellAddress(col, row))
        return result

    def _affected_formulas(self, changed: set[CellAddress]) -> set[CellAddress]:
        """All formulas reachable through reverse dependency edges."""
        affected: set[CellAddress] = set()
        stack = list(changed)
        while stack:
            cell = stack.pop()
            for formula in self.dependents.get(cell, ()):  # type: ignore[arg-type]
                if formula not in affected:
                    affected.add(formula)
                    stack.append(formula)
        return affected

    def _formula_closure(self, seeds: Iterable[CellAddress]) -> set[CellAddress]:
        """Seeds plus formulas that directly/indirectly evaluate them."""
        return self._affected_formulas(set(seeds)) | set(seeds)

    def _recompute_from(self, changed: set[CellAddress]) -> None:
        affected = self._affected_formulas(changed)

        # Include newly entered/changed formula itself.
        for root in changed:
            if root in self.ast:
                affected.add(root)

        if not affected:
            # Non-formula changed cell's cached raw evaluated value is derived
            # on demand, so no cache entry is necessary.
            return

        sub_deps = {f: self.dependencies.get(f, set()) & affected for f in affected}
        indegree = {f: len(deps) for f, deps in sub_deps.items()}
        queue = deque(f for f, degree in indegree.items() if degree == 0)
        visited: set[CellAddress] = set()

        while queue:
            formula = queue.popleft()
            if formula in visited:
                continue
            visited.add(formula)
            self.values[formula] = self._evaluate(formula)
            for dependent in self.dependents.get(formula, ()):  # type: ignore[arg-type]
                if dependent in indegree:
                    indegree[dependent] -= 1
                    if indegree[dependent] == 0:
                        queue.append(dependent)

        cyclic = affected - visited
        if cyclic:
            # Mark all cells in the strongly affected cycle. Formulas depending
            # on a cyclic formula are processed once it retains #CYCLE!.
            for addr in self._formula_closure(cyclic):
                if addr in affected or self._depends_on_cycle(addr, cyclic):
                    self.values[addr] = CycleErrorValue("circular reference")

    def _depends_on_cycle(
        self, formula: CellAddress, cyclic: set[CellAddress]
    ) -> bool:
        seen: set[CellAddress] = set()
        stack = [formula]
        while stack:
            current = stack.pop()
            if current in cyclic:
                return True
            if current in seen:
                continue
            seen.add(current)
            stack.extend(self.dependencies.get(current, set()))
        return False

    # ------------------------------- evaluation ----------------------------
    def raw_cell_value(self, addr: CellAddress) -> object:
        content = self.sheet.get_content(addr)
        if content == "":
            return None
        if content.startswith("="):
            # A formula should normally have a cache entry.
            return self.values.get(addr, 0.0)
        number = parse_number(content)
        if number is not None:
            return number
        return content

    def lookup(self, addr: CellAddress) -> object:
        if addr in self.ast:
            return self.values.get(addr)
        return self.raw_cell_value(addr)

    def _evaluate(self, formula: CellAddress) -> object:
        tree = self.ast.get(formula)
        if tree is None:
            return self.raw_cell_value(formula)
        return Evaluator(self.lookup).eval(tree)

    def value(self, addr: CellAddress) -> object:
        if addr in self.ast:
            return self.values.get(addr, 0.0)
        return self.raw_cell_value(addr)

    # Useful for REPL/tests.
    def is_formula(self, addr: CellAddress) -> bool:
        return addr in self.ast
