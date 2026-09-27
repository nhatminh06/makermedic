"""Synchronous orchestration of collection and interpretation."""

from collections.abc import Callable
from datetime import UTC, datetime

from makermedic.core.errors import ProbeCollectionError
from makermedic.core.evidence import EvidenceStore
from makermedic.core.graph import DiagnosticGraph
from makermedic.core.models import (
    DependencyState,
    DiagnosticResult,
    DiagnosticRun,
    DiagnosticStatus,
    ProbeOutcome,
    ProbeStatus,
    ResultOrigin,
)
from makermedic.core.registry import Registry


class DiagnosticEngine:
    """Run registered probes, then evaluate registered rules.

    Only ProbeCollectionError is an expected collection boundary: it is recorded
    and other probes continue. Duplicate evidence, rule failures, and unexpected
    exceptions propagate so programming and configuration defects stay visible.
    """

    def __init__(
        self,
        registry: Registry,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._registry = registry
        self._clock = clock or (lambda: datetime.now(UTC))
        self._graph = DiagnosticGraph(registry.rules())

    def run(self, category: str | None = None) -> DiagnosticRun:
        selected_rules = self._registry.rules(category)
        selected_ids = {rule.id for rule in selected_rules}
        ordered_ids = self._graph.topological_order(selected_ids)
        execution_categories = {
            self._graph.rule(diagnostic_id).category for diagnostic_id in ordered_ids
        }
        probes = tuple(
            probe
            for probe in self._registry.probes()
            if category is None
            or category in probe.categories
            or any(item in execution_categories for item in probe.categories)
        )
        evidence = EvidenceStore()
        outcomes: list[ProbeOutcome] = []

        for probe in probes:
            try:
                collected = tuple(probe.collect())
                evidence.extend(collected)
            except ProbeCollectionError as error:
                outcomes.append(
                    ProbeOutcome(
                        probe_id=probe.id,
                        status=ProbeStatus.FAILED,
                        error=str(error),
                    )
                )
            else:
                outcomes.append(
                    ProbeOutcome(
                        probe_id=probe.id,
                        status=ProbeStatus.SUCCESS,
                        evidence_keys=tuple(item.key for item in collected),
                    )
                )

        computed: dict[str, DiagnosticResult] = {}
        for diagnostic_id in ordered_ids:
            rule = self._graph.rule(diagnostic_id)
            blockers = tuple(
                dependency
                for dependency in self._graph.dependencies_of(diagnostic_id)
                if computed[dependency].dependency_state
                is not DependencyState.SATISFIED
            )
            if blockers:
                result = DiagnosticResult(
                    diagnostic_id=rule.id,
                    category=rule.category,
                    status=DiagnosticStatus.BLOCKED,
                    dependency_state=DependencyState.UNSATISFIED,
                    origin=ResultOrigin.DEPENDENCY_BLOCKED,
                    summary="Blocked by diagnostic prerequisites",
                    blocked_by=blockers,
                )
            else:
                result = rule.evaluate(evidence)
            computed[diagnostic_id] = result
        results = tuple(computed[node] for node in ordered_ids if node in selected_ids)
        return DiagnosticRun(
            timestamp=self._clock(),
            evidence=evidence.values(),
            probe_outcomes=tuple(outcomes),
            results=results,
        )
