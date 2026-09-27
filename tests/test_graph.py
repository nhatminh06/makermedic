from dataclasses import dataclass

import pytest

from makermedic.core.errors import (
    DiagnosticDependencyCycleError,
    DuplicateDiagnosticDependencyError,
    DuplicateRegistrationError,
    MissingDiagnosticDependencyError,
)
from makermedic.core.graph import DiagnosticGraph


@dataclass
class Rule:
    id: str
    dependencies: tuple[str, ...] = ()
    category: str = "test"
    required_evidence: frozenset[str] = frozenset()

    def evaluate(self, _evidence):
        raise NotImplementedError


def test_empty_and_single_node_graphs() -> None:
    assert DiagnosticGraph().topological_order() == ()
    assert DiagnosticGraph((Rule("a"),)).topological_order() == ("a",)


def test_independent_nodes_preserve_registration_order_deterministically() -> None:
    rules = (Rule("c"), Rule("a"), Rule("b"))
    assert DiagnosticGraph(rules).topological_order() == ("c", "a", "b")
    assert DiagnosticGraph(rules).topological_order() == ("c", "a", "b")


def test_chain_branching_convergence_and_multiple_dependencies() -> None:
    graph = DiagnosticGraph(
        (
            Rule("final", ("left", "right")),
            Rule("root"),
            Rule("right", ("root",)),
            Rule("left", ("root",)),
        )
    )
    assert graph.topological_order() == ("root", "right", "left", "final")
    assert graph.dependencies_of("final") == ("left", "right")
    assert graph.dependents_of("root") == ("right", "left")
    assert graph.ancestors_of("final") == ("root", "right", "left")
    assert graph.descendants_of("root") == ("right", "left", "final")
    assert graph.topological_order(("final",)) == (
        "root",
        "right",
        "left",
        "final",
    )


def test_missing_dependency_is_rejected() -> None:
    with pytest.raises(MissingDiagnosticDependencyError, match="missing"):
        DiagnosticGraph((Rule("a", ("missing",)),))


def test_duplicate_id_and_dependency_are_rejected() -> None:
    with pytest.raises(DuplicateRegistrationError):
        DiagnosticGraph((Rule("a"), Rule("a")))
    with pytest.raises(DuplicateDiagnosticDependencyError):
        DiagnosticGraph((Rule("a"), Rule("b", ("a", "a"))))


@pytest.mark.parametrize(
    "rules",
    [
        (Rule("a", ("a",)),),
        (Rule("a", ("b",)), Rule("b", ("a",))),
        (
            Rule("a", ("c",)),
            Rule("b", ("a",)),
            Rule("c", ("b",)),
        ),
    ],
)
def test_cycles_are_rejected(rules) -> None:
    with pytest.raises(DiagnosticDependencyCycleError, match="cycle"):
        DiagnosticGraph(rules)


def test_unknown_node_queries_fail_clearly() -> None:
    graph = DiagnosticGraph((Rule("a"),))
    with pytest.raises(KeyError, match="unknown diagnostic ID"):
        graph.dependencies_of("missing")
