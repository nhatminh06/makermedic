import pytest

from makermedic.core.evidence import EvidenceStore
from makermedic.core.models import DiagnosticStatus, Evidence, EvidenceAvailability
from makermedic.diagnostics.python import (
    PipConsistencyRule,
    PythonVersionRule,
    VirtualEnvironmentRule,
)
from makermedic.probes.python import PythonEnvironmentProbe, PythonRuntime


def evidence_store(**values: object) -> EvidenceStore:
    return EvidenceStore(
        Evidence(key=key.replace("__", "."), source="test", value=value)
        for key, value in values.items()
    )


@pytest.mark.parametrize(
    ("version", "expected"),
    [([3, 12, 0], DiagnosticStatus.PASS), ([3, 11, 9], DiagnosticStatus.FAIL)],
)
def test_python_version_rule(version: list[int], expected: DiagnosticStatus) -> None:
    result = PythonVersionRule().evaluate(evidence_store(python__version_info=version))

    assert result.status is expected


@pytest.mark.parametrize(
    ("in_virtualenv", "expected"),
    [(True, DiagnosticStatus.PASS), (False, DiagnosticStatus.WARN)],
)
def test_virtual_environment_rule(
    in_virtualenv: bool, expected: DiagnosticStatus
) -> None:
    result = VirtualEnvironmentRule().evaluate(
        evidence_store(
            python__in_virtualenv=in_virtualenv,
            python__venv__type="venv" if in_virtualenv else "none",
        )
    )

    assert result.status is expected


def test_unknown_virtual_environment_state() -> None:
    unavailable = Evidence(
        key="python.in_virtualenv",
        source="test",
        availability=EvidenceAvailability.UNAVAILABLE,
    )

    result = VirtualEnvironmentRule().evaluate(EvidenceStore([unavailable]))

    assert result.status is DiagnosticStatus.UNKNOWN


def test_python_probe_serializes_executable_and_prefixes() -> None:
    runtime = PythonRuntime(
        version="3.12.1",
        version_info=(3, 12, 1),
        implementation="cpython",
        executable="/project/.venv/bin/python",
        prefix="/project/.venv",
        base_prefix="/usr",
    )

    collected = {
        item.key: item for item in PythonEnvironmentProbe(runtime, {}).collect()
    }

    assert collected["python.executable"].value == "/project/.venv/bin/python"
    assert collected["python.prefix"].value == "/project/.venv"
    assert collected["python.base_prefix"].value == "/usr"
    assert collected["python.in_virtualenv"].value is True
    assert collected["python.venv.type"].value == "venv"


def pip_store(
    *,
    module_available: bool,
    path_available: bool,
    module_location: str | None = None,
    path_location: str | None = None,
) -> EvidenceStore:
    return evidence_store(
        python__executable="/project/.venv/bin/python",
        python__pip__module__available=module_available,
        python__pip__module__location=module_location,
        python__pip__path__command="/usr/bin/pip" if path_available else None,
        python__pip__path__available=path_available,
        python__pip__path__location=path_location,
    )


def test_coherent_pip_environment_passes() -> None:
    result = PipConsistencyRule().evaluate(
        pip_store(
            module_available=True,
            path_available=True,
            module_location="/project/.venv/lib/python3.12/site-packages/pip",
            path_location="/project/.venv/lib/python3.12/site-packages/pip",
        )
    )

    assert result.status is DiagnosticStatus.PASS


def test_mismatched_path_pip_warns() -> None:
    result = PipConsistencyRule().evaluate(
        pip_store(
            module_available=True,
            path_available=True,
            module_location="/project/.venv/lib/python3.12/site-packages/pip",
            path_location="/usr/lib/python3/site-packages/pip",
        )
    )

    assert result.status is DiagnosticStatus.WARN
    assert "python -m pip" in result.recommendations[0]


def test_path_pip_absent_but_module_pip_works_warns() -> None:
    result = PipConsistencyRule().evaluate(
        pip_store(module_available=True, path_available=False)
    )

    assert result.status is DiagnosticStatus.WARN


def test_all_pip_unavailable_is_unknown() -> None:
    result = PipConsistencyRule().evaluate(
        pip_store(module_available=False, path_available=False)
    )

    assert result.status is DiagnosticStatus.UNKNOWN
