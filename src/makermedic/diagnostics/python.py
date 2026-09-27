"""Deterministic rules for Python environment evidence."""

import os

from makermedic.core.evidence import EvidenceStore
from makermedic.core.models import (
    DependencyState,
    DiagnosticResult,
    DiagnosticStatus,
    EvidenceAvailability,
    FindingKind,
    dependency_state_for_status,
)


class PythonVersionRule:
    id = "python.version.support"
    category = "python"
    dependencies = ()
    required_evidence = frozenset({"python.version_info"})

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        version = _version_info(evidence)
        if version is None:
            status = DiagnosticStatus.UNKNOWN
            summary = "Python version could not be determined"
        elif version >= (3, 12):
            status = DiagnosticStatus.PASS
            summary = f"Python {version[0]}.{version[1]} is supported"
        else:
            status = DiagnosticStatus.FAIL
            summary = f"Python {version[0]}.{version[1]} is unsupported"
        return DiagnosticResult(
            diagnostic_id=self.id,
            category=self.category,
            status=status,
            dependency_state=dependency_state_for_status(status),
            summary=summary,
            evidence=("python.version_info",),
            recommendations=("Run MakerMedic with Python 3.12 or newer.",)
            if status is DiagnosticStatus.FAIL
            else (),
        )


class VirtualEnvironmentRule:
    id = "python.virtual_environment"
    category = "python"
    dependencies = ()
    required_evidence = frozenset({"python.in_virtualenv", "python.venv.type"})

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        in_virtualenv = _typed_value(evidence, "python.in_virtualenv", bool)
        environment_type = _typed_value(evidence, "python.venv.type", str)
        if in_virtualenv is None:
            status = DiagnosticStatus.UNKNOWN
            summary = "Virtual environment state could not be determined"
        elif in_virtualenv:
            status = DiagnosticStatus.PASS
            summary = f"Python virtual environment ({environment_type or 'unknown'})"
        else:
            status = DiagnosticStatus.WARN
            summary = "Python is not running in a virtual environment"
        return DiagnosticResult(
            diagnostic_id=self.id,
            category=self.category,
            status=status,
            dependency_state=dependency_state_for_status(
                status, warning=DependencyState.SATISFIED
            ),
            summary=summary,
            evidence=("python.in_virtualenv", "python.venv.type"),
            recommendations=("Use an isolated virtual environment for development.",)
            if status is DiagnosticStatus.WARN
            else (),
        )


class PipConsistencyRule:
    """Conservatively compare parsed pip distribution locations."""

    id = "python.pip.consistency"
    category = "python"
    dependencies = ()
    required_evidence = frozenset(
        {
            "python.executable",
            "python.pip.module.available",
            "python.pip.module.location",
            "python.pip.path.command",
            "python.pip.path.available",
            "python.pip.path.location",
        }
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        python = _typed_value(evidence, "python.executable", str)
        module_available = _typed_value(evidence, "python.pip.module.available", bool)
        path_available = _typed_value(evidence, "python.pip.path.available", bool)
        module_location = _typed_value(evidence, "python.pip.module.location", str)
        path_location = _typed_value(evidence, "python.pip.path.location", str)
        path_command = _typed_value(evidence, "python.pip.path.command", str)

        causes = _pip_causes(python, path_command)
        recommendation = ("Use `python -m pip` for this environment.",)
        if module_available is None or path_available is None:
            status = DiagnosticStatus.UNKNOWN
            summary = "pip and Python consistency could not be determined"
        elif not module_available:
            status = DiagnosticStatus.UNKNOWN
            summary = "Python-bound pip is unavailable"
        elif not path_available:
            status = DiagnosticStatus.WARN
            summary = "PATH pip is unavailable; Python-bound pip works"
        elif module_location is None or path_location is None:
            status = DiagnosticStatus.UNKNOWN
            summary = "pip locations could not be determined"
        elif _normal_path(module_location) == _normal_path(path_location):
            status = DiagnosticStatus.PASS
            summary = "pip and Python environment are coherent"
        else:
            status = DiagnosticStatus.WARN
            summary = "PATH pip appears to belong to another Python environment"
        return DiagnosticResult(
            diagnostic_id=self.id,
            category=self.category,
            status=status,
            dependency_state=dependency_state_for_status(
                status, warning=DependencyState.SATISFIED
            ),
            summary=summary,
            evidence=tuple(sorted(self.required_evidence)),
            causes=causes
            if status in {DiagnosticStatus.WARN, DiagnosticStatus.UNKNOWN}
            else (),
            recommendations=recommendation
            if status in {DiagnosticStatus.WARN, DiagnosticStatus.UNKNOWN}
            else (),
        )


class PackageInspectionRule:
    id = "python.package.inspection"
    category = "python"
    dependencies = ()
    required_evidence = frozenset(
        {
            "python.package.requested",
            "python.package.installed",
            "python.package.version",
            "python.package.metadata_location",
        }
    )

    def evaluate(self, evidence: EvidenceStore) -> DiagnosticResult:
        package = _typed_value(evidence, "python.package.requested", str)
        installed = _typed_value(evidence, "python.package.installed", bool)
        version = _typed_value(evidence, "python.package.version", str)
        if package is None or installed is None:
            status = DiagnosticStatus.UNKNOWN
            summary = "Package metadata could not be inspected"
        elif installed:
            status = DiagnosticStatus.PASS
            summary = f"Package {package} {version or '(version unknown)'} is installed"
        else:
            status = DiagnosticStatus.WARN
            summary = f"Package {package} is not installed"
        return DiagnosticResult(
            diagnostic_id=self.id,
            category=self.category,
            status=status,
            dependency_state=dependency_state_for_status(
                status, warning=DependencyState.UNSATISFIED
            ),
            finding_kind=FindingKind.MISSING_CAPABILITY
            if status is DiagnosticStatus.WARN
            else None,
            summary=summary,
            evidence=tuple(sorted(self.required_evidence)),
        )


def _typed_value[T](evidence: EvidenceStore, key: str, expected: type[T]) -> T | None:
    item = evidence.get(key)
    if (
        item is None
        or item.availability is EvidenceAvailability.UNAVAILABLE
        or not isinstance(item.value, expected)
    ):
        return None
    return item.value


def _version_info(evidence: EvidenceStore) -> tuple[int, int] | None:
    item = evidence.get("python.version_info")
    if item is None or item.availability is EvidenceAvailability.UNAVAILABLE:
        return None
    value = item.value
    if (
        not isinstance(value, list)
        or len(value) < 2
        or isinstance(value[0], bool)
        or isinstance(value[1], bool)
        or not isinstance(value[0], int)
        or not isinstance(value[1], int)
    ):
        return None
    return value[0], value[1]


def _normal_path(value: str) -> str:
    return os.path.normcase(os.path.normpath(value))


def _pip_causes(python: str | None, path_command: str | None) -> tuple[str, ...]:
    values = []
    if python:
        values.append(f"Current Python: {python}")
    if path_command:
        values.append(f"PATH pip: {path_command}")
    return tuple(values)
