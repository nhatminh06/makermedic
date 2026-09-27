"""Pure deterministic interpretation of diagnostic results and graph structure."""

from makermedic.core.graph import DiagnosticGraph
from makermedic.core.models import (
    DependencyState,
    DiagnosticRun,
    DiagnosticStatus,
    FindingKind,
    ResultOrigin,
    RootCauseAnalysis,
    RootFinding,
)


class RootCauseAnalyzer:
    """Identify directly evaluated upstream findings and current impacts."""

    def analyze(self, run: DiagnosticRun, graph: DiagnosticGraph) -> RootCauseAnalysis:
        results = {}
        for result in run.results:
            graph.rule(result.diagnostic_id)
            if result.diagnostic_id in results:
                raise ValueError(f"duplicate diagnostic result: {result.diagnostic_id}")
            results[result.diagnostic_id] = result
        order = graph.topological_order()
        positions = {diagnostic_id: index for index, diagnostic_id in enumerate(order)}
        findings: list[RootFinding] = []

        for diagnostic_id in order:
            result = results.get(diagnostic_id)
            if result is None or not self._eligible(result, results, graph):
                continue
            kind = result.finding_kind
            if kind is None:
                continue
            affected = tuple(
                descendant
                for descendant in graph.descendants_of(diagnostic_id)
                if descendant in results
                and results[descendant].dependency_state
                is not DependencyState.SATISFIED
            )
            findings.append(
                RootFinding(
                    diagnostic_id=result.diagnostic_id,
                    category=result.category,
                    status=result.status,
                    dependency_state=result.dependency_state,
                    kind=kind,
                    summary=result.summary,
                    affected_diagnostics=affected,
                    recommendations=result.recommendations,
                    evidence_refs=result.evidence,
                )
            )

        priority = {
            FindingKind.FAILURE: 0,
            FindingKind.MISSING_CAPABILITY: 1,
            FindingKind.UNCERTAIN: 2,
            FindingKind.OPTIONAL_ABSENCE: 3,
            FindingKind.SUPPORTING: 4,
        }
        findings.sort(
            key=lambda finding: (
                priority[finding.kind],
                -len(finding.affected_diagnostics),
                positions[finding.diagnostic_id],
                finding.diagnostic_id,
            )
        )
        return RootCauseAnalysis(
            actionable_findings=tuple(
                finding
                for finding in findings
                if finding.kind in {FindingKind.FAILURE, FindingKind.MISSING_CAPABILITY}
            ),
            unresolved_findings=tuple(
                finding for finding in findings if finding.kind is FindingKind.UNCERTAIN
            ),
            optional_absences=tuple(
                finding
                for finding in findings
                if finding.kind is FindingKind.OPTIONAL_ABSENCE
            ),
            supporting_findings=tuple(
                finding
                for finding in findings
                if finding.kind is FindingKind.SUPPORTING
            ),
            blocked_diagnostics=tuple(
                diagnostic_id
                for diagnostic_id in order
                if diagnostic_id in results
                and results[diagnostic_id].origin is ResultOrigin.DEPENDENCY_BLOCKED
            ),
            healthy_count=sum(
                result.dependency_state is DependencyState.SATISFIED
                for result in run.results
            ),
        )

    @staticmethod
    def _eligible(result, results, graph: DiagnosticGraph) -> bool:
        if result.origin is not ResultOrigin.EVALUATED:
            return False
        if result.status is DiagnosticStatus.BLOCKED:
            return False
        if result.dependency_state is DependencyState.SATISFIED:
            return False
        return not any(
            ancestor in results
            and results[ancestor].dependency_state is not DependencyState.SATISFIED
            for ancestor in graph.ancestors_of(result.diagnostic_id)
        )
