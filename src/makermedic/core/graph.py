"""Validated deterministic graph of diagnostic prerequisites."""

from collections.abc import Iterable, Sequence

from makermedic.core.errors import (
    DiagnosticDependencyCycleError,
    DuplicateDiagnosticDependencyError,
    DuplicateRegistrationError,
    MissingDiagnosticDependencyError,
)
from makermedic.core.rules import DiagnosticRule


class DiagnosticGraph:
    """A small directed acyclic graph over registered diagnostic rules."""

    def __init__(self, rules: Sequence[DiagnosticRule] = ()) -> None:
        self._rules: dict[str, DiagnosticRule] = {}
        self._position: dict[str, int] = {}
        self._dependencies: dict[str, tuple[str, ...]] = {}
        for position, rule in enumerate(rules):
            if rule.id in self._rules:
                raise DuplicateRegistrationError(f"duplicate rule ID: {rule.id}")
            dependencies = tuple(getattr(rule, "dependencies", ()))
            if len(dependencies) != len(set(dependencies)):
                raise DuplicateDiagnosticDependencyError(
                    f"duplicate dependency declared by {rule.id}"
                )
            self._rules[rule.id] = rule
            self._position[rule.id] = position
            self._dependencies[rule.id] = dependencies
        self._validate_references()
        self._order = self._topological_sort()

    def rule(self, diagnostic_id: str) -> DiagnosticRule:
        try:
            return self._rules[diagnostic_id]
        except KeyError as error:
            raise KeyError(f"unknown diagnostic ID: {diagnostic_id}") from error

    def dependencies_of(self, diagnostic_id: str) -> tuple[str, ...]:
        self.rule(diagnostic_id)
        return self._dependencies[diagnostic_id]

    def dependents_of(self, diagnostic_id: str) -> tuple[str, ...]:
        self.rule(diagnostic_id)
        return tuple(
            node for node in self._order if diagnostic_id in self._dependencies[node]
        )

    def ancestors_of(self, diagnostic_id: str) -> tuple[str, ...]:
        self.rule(diagnostic_id)
        found: set[str] = set()

        def visit(node: str) -> None:
            for dependency in self._dependencies[node]:
                if dependency not in found:
                    found.add(dependency)
                    visit(dependency)

        visit(diagnostic_id)
        return tuple(node for node in self._order if node in found)

    def descendants_of(self, diagnostic_id: str) -> tuple[str, ...]:
        self.rule(diagnostic_id)
        found: set[str] = set()

        def visit(node: str) -> None:
            for dependent in self.dependents_of(node):
                if dependent not in found:
                    found.add(dependent)
                    visit(dependent)

        visit(diagnostic_id)
        return tuple(node for node in self._order if node in found)

    def topological_order(
        self, selected: Iterable[str] | None = None
    ) -> tuple[str, ...]:
        if selected is None:
            return self._order
        included: set[str] = set()
        for diagnostic_id in selected:
            self.rule(diagnostic_id)
            included.add(diagnostic_id)
            included.update(self.ancestors_of(diagnostic_id))
        return tuple(node for node in self._order if node in included)

    def _validate_references(self) -> None:
        for node, dependencies in self._dependencies.items():
            for dependency in dependencies:
                if dependency not in self._rules:
                    raise MissingDiagnosticDependencyError(
                        f"{node} depends on missing diagnostic {dependency}"
                    )

    def _topological_sort(self) -> tuple[str, ...]:
        indegree = {
            node: len(dependencies) for node, dependencies in self._dependencies.items()
        }
        ready = [node for node in self._rules if indegree[node] == 0]
        order: list[str] = []
        while ready:
            ready.sort(key=self._position.__getitem__)
            node = ready.pop(0)
            order.append(node)
            for dependent in self._rules:
                if node not in self._dependencies[dependent]:
                    continue
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
        if len(order) != len(self._rules):
            involved = tuple(node for node in self._rules if indegree[node] > 0)
            raise DiagnosticDependencyCycleError(
                f"diagnostic dependency cycle involving: {', '.join(involved)}"
            )
        return tuple(order)
