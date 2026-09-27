"""Explicit, ordered registration of probes and diagnostic rules."""

from makermedic.core.errors import (
    DuplicateRegistrationError,
    UnknownCategoryError,
)
from makermedic.core.probe import Probe
from makermedic.core.rules import DiagnosticRule


class Registry:
    """A small explicit registry; no discovery or global mutable state."""

    def __init__(self) -> None:
        self._probes: dict[str, Probe] = {}
        self._rules: dict[str, DiagnosticRule] = {}

    def register_probe(self, probe: Probe) -> None:
        if probe.id in self._probes:
            raise DuplicateRegistrationError(f"duplicate probe ID: {probe.id}")
        self._probes[probe.id] = probe

    def register_rule(self, rule: DiagnosticRule) -> None:
        if rule.id in self._rules:
            raise DuplicateRegistrationError(f"duplicate rule ID: {rule.id}")
        self._rules[rule.id] = rule

    @property
    def categories(self) -> frozenset[str]:
        probe_categories = {
            category for probe in self._probes.values() for category in probe.categories
        }
        rule_categories = {rule.category for rule in self._rules.values()}
        return frozenset(probe_categories | rule_categories)

    def probes(self, category: str | None = None) -> tuple[Probe, ...]:
        self._validate_category(category)
        return tuple(
            probe
            for probe in self._probes.values()
            if category is None or category in probe.categories
        )

    def rules(self, category: str | None = None) -> tuple[DiagnosticRule, ...]:
        self._validate_category(category)
        return tuple(
            rule
            for rule in self._rules.values()
            if category is None or category == rule.category
        )

    def _validate_category(self, category: str | None) -> None:
        if category is not None and category not in self.categories:
            raise UnknownCategoryError(f"unknown diagnostic category: {category}")
