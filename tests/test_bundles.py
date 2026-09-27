import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from makermedic.core.bundles import (
    ARCHIVE_ROOT,
    BundleBuilder,
    BundleOutputExistsError,
    EvidenceExportPolicy,
    export_bundle,
    render_bundle_files,
)
from makermedic.core.errors import BundleWriteError
from makermedic.core.models import (
    DiagnosticResult,
    DiagnosticRun,
    DiagnosticStatus,
    Evidence,
    RootCauseAnalysis,
    RootFinding,
)
from makermedic.core.snapshots import snapshot_from_run

NOW = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
SECRETS = (
    "SECRET_TOKEN_123",
    "password=hunter2",
    "Authorization: Bearer abc",
    "/home/example-user/private",
    "usb-serial-123456",
)


def sample_run(*evidence: Evidence) -> DiagnosticRun:
    finding = RootFinding(
        diagnostic_id="gpu.driver",
        category="gpu",
        status=DiagnosticStatus.FAIL,
        dependency_state="UNSATISFIED",
        kind="FAILURE",
        summary="Driver communication failed",
        recommendations=("Review the installed driver.",),
        evidence_refs=("gpu.nvidia.driver.available",),
    )
    return DiagnosticRun(
        timestamp=NOW,
        evidence=evidence,
        probe_outcomes=(),
        results=(
            DiagnosticResult(
                diagnostic_id="gpu.driver",
                category="gpu",
                status=DiagnosticStatus.FAIL,
                summary="Driver communication failed",
                recommendations=("Review the installed driver.",),
                evidence=("gpu.nvidia.driver.available",),
            ),
        ),
        root_cause_analysis=RootCauseAnalysis(
            actionable_findings=(finding,), healthy_count=0
        ),
    )


def test_allowlist_exports_safe_values_and_omits_unknown_and_paths() -> None:
    run = sample_run(
        Evidence(key="system.os", source="test", value="Linux"),
        Evidence(key="python.version", source="test", value="3.14.0"),
        Evidence(
            key="python.executable", source="test", value="/home/example-user/private"
        ),
        Evidence(key="environment.API_TOKEN", source="test", value="SECRET_TOKEN_123"),
        Evidence(key="gpu.nvidia.driver.version", source="test", value="555.1"),
    )
    plan = BundleBuilder().from_run(run)

    assert plan.exported_evidence == ("gpu.nvidia.driver.version",)
    assert plan.omitted_evidence == ("environment.API_TOKEN", "python.executable")
    serialized = plan.model_dump_json()
    assert "SECRET_TOKEN_123" not in serialized
    assert "/home/example-user/private" not in serialized
    policy = EvidenceExportPolicy()
    assert policy.export(run.evidence[0]) is not None
    assert policy.export(run.evidence[1]) is not None


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("usb.devices", [{"vendor_id": "1234", "serial": "usb-serial-123456"}]),
        ("service.http.response_body", "password=hunter2"),
        ("service.http.headers", {"Authorization": "Bearer abc"}),
        ("service.http.cookies", "SECRET_TOKEN_123"),
        ("camera.frame.pixels", "SECRET_TOKEN_123"),
        ("camera.frame.path", "/home/example-user/private"),
        ("serial.traffic", "password=hunter2"),
        ("process.command_line", "Authorization: Bearer abc"),
        ("logs.dmesg", "SECRET_TOKEN_123"),
    ],
)
def test_sensitive_values_never_enter_plan(key: str, value) -> None:
    plan = BundleBuilder().from_run(
        sample_run(Evidence(key=key, source="test", value=value))
    )
    text = plan.model_dump_json()
    assert all(secret not in text for secret in SECRETS)


def test_structured_allowlists_strip_nested_fields() -> None:
    policy = EvidenceExportPolicy()
    exported = policy.export(
        Evidence(
            key="serial.devices",
            source="test",
            value=[
                {
                    "path": "/dev/ttyACM0",
                    "readable": True,
                    "command_line": "password=hunter2",
                    "usb": {
                        "vendor_id": "2341",
                        "product_id": "0043",
                        "serial": "usb-serial-123456",
                    },
                }
            ],
        )
    )
    assert exported is not None
    assert exported.value == [
        {
            "path": "/dev/ttyACM0",
            "readable": True,
            "usb": {"vendor_id": "2341", "product_id": "0043"},
        }
    ]


def test_plan_inventory_ordering_and_category_filtering() -> None:
    plan = BundleBuilder().from_run(
        sample_run(
            Evidence(key="gpu.pytorch.version", source="test", value="2.8"),
            Evidence(key="system.kernel", source="test", value="6.1"),
        )
    )
    assert plan.manifest.file_inventory == tuple(sorted(plan.manifest.file_inventory))
    assert plan.exported_evidence == tuple(sorted(plan.exported_evidence))
    assert {item.category for item in plan.category_files} == {"gpu"}
    assert "system.json" not in plan.manifest.file_inventory


def test_snapshot_plan_has_diagnostics_findings_but_no_evidence_files() -> None:
    snapshot = snapshot_from_run(sample_run(), category_filter="gpu")
    plan = BundleBuilder().from_snapshot(snapshot)
    assert plan.manifest.source_type == "snapshot"
    assert plan.diagnostics[0].diagnostic_id == "gpu.driver"
    assert plan.findings[0].diagnostic_id == "gpu.driver"
    assert plan.category_files == ()
    assert plan.exported_evidence == ()
    assert plan.manifest.file_inventory == tuple(
        sorted(("diagnostics.json", "findings.json", "manifest.json", "summary.txt"))
    )
    assert "Evidence values are absent" in plan.summary


def test_valid_zip_static_members_json_utf8_and_same_plan(tmp_path: Path) -> None:
    plan = BundleBuilder().from_run(
        sample_run(Evidence(key="gpu.pytorch.version", source="test", value="2.8"))
    )
    destination = tmp_path / "support.zip"
    export_bundle(plan, destination)
    expected = render_bundle_files(plan)
    with zipfile.ZipFile(destination) as archive:
        assert archive.namelist() == [
            f"{ARCHIVE_ROOT}/{name}" for name in sorted(expected)
        ]
        assert all(
            ".." not in name and not name.startswith("/") for name in archive.namelist()
        )
        for name, content in expected.items():
            assert archive.read(f"{ARCHIVE_ROOT}/{name}") == content
            if name.endswith(".json"):
                json.loads(content)
        archive.read(f"{ARCHIVE_ROOT}/summary.txt").decode("utf-8")
    assert list(tmp_path.glob("*.tmp")) == []


def test_zip_secret_scan(tmp_path: Path) -> None:
    evidence = [
        Evidence(key=f"private.fixture.{index}", source="test", value=value)
        for index, value in enumerate(SECRETS)
    ]
    plan = BundleBuilder().from_run(sample_run(*evidence))
    destination = tmp_path / "support.zip"
    export_bundle(plan, destination)
    with zipfile.ZipFile(destination) as archive:
        content = b"\n".join(archive.read(name) for name in archive.namelist()).decode()
    assert all(secret not in content for secret in SECRETS)


def test_existing_refused_force_overwrites_and_temp_cleanup(tmp_path: Path) -> None:
    destination = tmp_path / "support.zip"
    destination.write_text("original", encoding="utf-8")
    plan = BundleBuilder().from_run(sample_run())
    with pytest.raises(BundleOutputExistsError):
        export_bundle(plan, destination)
    assert destination.read_text(encoding="utf-8") == "original"
    export_bundle(plan, destination, force=True)
    assert zipfile.is_zipfile(destination)
    assert list(tmp_path.glob("*.tmp")) == []


def test_zip_failure_leaves_no_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class BrokenZip:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            raise OSError("simulated ZIP failure")

        def __exit__(self, *_args) -> None:
            pass

    monkeypatch.setattr("makermedic.core.bundles.zipfile.ZipFile", BrokenZip)
    destination = tmp_path / "support.zip"
    with pytest.raises(BundleWriteError):
        export_bundle(BundleBuilder().from_run(sample_run()), destination)
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []
