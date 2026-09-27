import json
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import FakeRule
from typer.testing import CliRunner

from makermedic.cli import app
from makermedic.core.models import DiagnosticStatus
from makermedic.core.registry import Registry

runner = CliRunner()


def registry_with_status(status: DiagnosticStatus) -> Registry:
    registry = Registry()
    registry.register_rule(FakeRule(status=status))
    return registry


def test_cli_help() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "diagnose" in result.stdout
    assert "bundle" in result.stdout
    assert "lab" in result.stdout


def test_cli_version_uses_package_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout == "MakerMedic 0.1.0\n"


def test_lab_list_and_json_are_deterministic() -> None:
    human = runner.invoke(app, ["lab", "list"])
    structured = runner.invoke(app, ["lab", "list", "--json"])
    assert human.exit_code == structured.exit_code == 0
    assert "simulated or use isolated" not in human.stdout
    payload = json.loads(structured.stdout)
    identifiers = [item["id"] for item in payload]
    assert len(identifiers) == 39
    assert identifiers == sorted(identifiers)


def test_lab_help_states_host_safety() -> None:
    result = runner.invoke(app, ["lab", "--help"])
    assert result.exit_code == 0
    assert "no intentional" in result.stdout
    assert "drivers" in result.stdout


def test_lab_show_and_run_json() -> None:
    shown = runner.invoke(app, ["lab", "show", "gpu-driver-unavailable", "--json"])
    executed = runner.invoke(app, ["lab", "run", "gpu-driver-unavailable", "--json"])
    assert shown.exit_code == executed.exit_code == 0
    assert json.loads(shown.stdout)["safety_level"] == "SIMULATED"
    assert json.loads(executed.stdout)["passed"] is True


def test_lab_unknown_scenario_is_usage_error() -> None:
    result = runner.invoke(app, ["lab", "run", "missing-scenario"])
    assert result.exit_code == 2
    assert "unknown lab scenario" in result.stderr


def test_bundle_requires_exactly_one_mode() -> None:
    assert runner.invoke(app, ["bundle"]).exit_code == 2
    result = runner.invoke(app, ["bundle", "--preview", "--output", "support.zip"])
    assert result.exit_code == 2


def test_bundle_preview_creates_no_zip(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "makermedic.cli.create_registry", lambda _package=None, **_kwargs: Registry()
    )
    result = runner.invoke(app, ["bundle", "--preview"])
    assert result.exit_code == 0
    assert "Support Bundle Preview" in result.stdout
    assert "manifest.json" in result.stdout
    assert "No environment variables" in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_bundle_live_serial_open_is_opt_in(monkeypatch) -> None:
    received = {}

    def registry(_package=None, **kwargs):
        received.update(kwargs)
        return Registry()

    monkeypatch.setattr("makermedic.cli.create_registry", registry)
    result = runner.invoke(app, ["bundle", "--category", "serial", "--preview"])
    assert result.exit_code == 2  # empty fake registry has no serial category
    assert received["serial_open_test"] is False
    result = runner.invoke(
        app,
        ["bundle", "--category", "serial", "--serial-open-test", "--preview"],
    )
    assert result.exit_code == 2
    assert received["serial_open_test"] is True


def test_bundle_snapshot_rejects_live_options(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "bundle",
            "--snapshot",
            str(tmp_path / "x.json"),
            "--category",
            "gpu",
            "--preview",
        ],
    )
    assert result.exit_code == 2
    assert "cannot be combined" in result.stderr


def test_bundle_service_requires_local_url() -> None:
    assert (
        runner.invoke(app, ["bundle", "--category", "service", "--preview"]).exit_code
        == 2
    )


def test_bundle_invalid_snapshot_is_usage_error(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"schema_version": 999}', encoding="utf-8")
    result = runner.invoke(app, ["bundle", "--snapshot", str(invalid), "--preview"])
    assert result.exit_code == 2
    assert "unsupported snapshot schema" in result.stderr
    assert (
        runner.invoke(
            app,
            [
                "bundle",
                "--category",
                "service",
                "--url",
                "http://example.com",
                "--preview",
            ],
        ).exit_code
        == 2
    )


def test_cli_diagnose_empty_registry() -> None:
    with patch("makermedic.cli.create_registry", return_value=Registry()):
        result = runner.invoke(app, ["diagnose"])

    assert result.exit_code == 0
    assert "No diagnostics are registered yet." in result.stdout


def test_cli_json_is_valid_and_unmixed() -> None:
    with patch("makermedic.cli.create_registry", return_value=Registry()):
        result = runner.invoke(app, ["diagnose", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["evidence"] == []
    assert payload["results"] == []
    assert "MakerMedic" not in result.stdout


@pytest.mark.parametrize(
    ("status", "exit_code"),
    [
        (DiagnosticStatus.PASS, 0),
        (DiagnosticStatus.WARN, 0),
        (DiagnosticStatus.UNKNOWN, 0),
        (DiagnosticStatus.BLOCKED, 0),
        (DiagnosticStatus.FAIL, 1),
    ],
)
def test_cli_exit_code_semantics(
    monkeypatch: pytest.MonkeyPatch,
    status: DiagnosticStatus,
    exit_code: int,
) -> None:
    monkeypatch.setattr(
        "makermedic.cli.create_registry",
        lambda _package=None, **_kwargs: registry_with_status(status),
    )

    result = runner.invoke(app, ["diagnose"])

    assert result.exit_code == exit_code


def test_cli_category_filtering(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = Registry()
    registry.register_rule(FakeRule(id="rule.example", category="example"))
    registry.register_rule(FakeRule(id="rule.other", category="other"))
    monkeypatch.setattr(
        "makermedic.cli.create_registry", lambda _package=None, **_kwargs: registry
    )

    result = runner.invoke(app, ["diagnose", "--category", "other", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["results"][0]["diagnostic_id"] == "rule.other"


def test_cli_unknown_category_is_usage_error() -> None:
    result = runner.invoke(app, ["diagnose", "--category", "missing"])

    assert result.exit_code == 2
    assert "unknown diagnostic category" in result.stderr


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [(DiagnosticStatus.WARN, 0), (DiagnosticStatus.FAIL, 1)],
)
def test_gpu_category_exit_semantics(
    monkeypatch: pytest.MonkeyPatch,
    status: DiagnosticStatus,
    expected_exit: int,
) -> None:
    registry = Registry()
    registry.register_rule(FakeRule(id="gpu.test", category="gpu", status=status))
    monkeypatch.setattr(
        "makermedic.cli.create_registry", lambda _package=None, **_kwargs: registry
    )

    result = runner.invoke(app, ["diagnose", "--category", "gpu", "--json"])

    assert result.exit_code == expected_exit
    assert json.loads(result.stdout)["results"][0]["category"] == "gpu"


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [(DiagnosticStatus.WARN, 0), (DiagnosticStatus.FAIL, 1)],
)
def test_camera_category_exit_semantics(
    monkeypatch: pytest.MonkeyPatch,
    status: DiagnosticStatus,
    expected_exit: int,
) -> None:
    registry = Registry()
    registry.register_rule(FakeRule(id="camera.test", category="camera", status=status))
    monkeypatch.setattr(
        "makermedic.cli.create_registry", lambda _package=None, **_kwargs: registry
    )
    result = runner.invoke(app, ["diagnose", "--category", "camera", "--json"])
    assert result.exit_code == expected_exit
    assert json.loads(result.stdout)["results"][0]["category"] == "camera"


@pytest.mark.parametrize("category", ["usb", "serial"])
@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [(DiagnosticStatus.WARN, 0), (DiagnosticStatus.FAIL, 1)],
)
def test_usb_serial_category_exit_semantics(
    monkeypatch: pytest.MonkeyPatch,
    category: str,
    status: DiagnosticStatus,
    expected_exit: int,
) -> None:
    registry = Registry()
    registry.register_rule(
        FakeRule(id=f"{category}.test", category=category, status=status)
    )
    monkeypatch.setattr(
        "makermedic.cli.create_registry", lambda _package=None, **_kwargs: registry
    )
    result = runner.invoke(app, ["diagnose", "--category", category, "--json"])
    assert result.exit_code == expected_exit
    assert json.loads(result.stdout)["results"][0]["category"] == category


def test_serial_open_option_requires_serial_category() -> None:
    result = runner.invoke(app, ["diagnose", "--category", "usb", "--serial-open-test"])
    assert result.exit_code == 2
    assert "serial open testing requires" in result.stderr
    assert "--category serial" in result.stderr


def test_serial_open_option_is_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, bool] = {}

    def registry(_package=None, *, serial_open_test=False):
        received["serial_open_test"] = serial_open_test
        value = Registry()
        value.register_rule(FakeRule(id="serial.test", category="serial"))
        return value

    monkeypatch.setattr("makermedic.cli.create_registry", registry)
    result = runner.invoke(
        app, ["diagnose", "--category", "serial", "--serial-open-test"]
    )
    assert result.exit_code == 0
    assert received == {"serial_open_test": True}


def test_service_requires_url() -> None:
    result = runner.invoke(app, ["diagnose", "--category", "service"])
    assert result.exit_code == 2
    assert "require --url" in result.stderr


@pytest.mark.parametrize("url", ["not-a-url", "ftp://localhost", "http://example.com"])
def test_service_rejects_invalid_or_external_url(url: str) -> None:
    result = runner.invoke(app, ["diagnose", "--category", "service", "--url", url])
    assert result.exit_code == 2


def test_url_requires_explicit_service_category() -> None:
    result = runner.invoke(app, ["diagnose", "--url", "http://localhost:8000"])
    assert result.exit_code == 2
    assert "--category service" in result.stderr


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [(DiagnosticStatus.PASS, 0), (DiagnosticStatus.FAIL, 1)],
)
def test_service_cli_forwards_target_and_exit_status(
    monkeypatch, status, expected_exit
) -> None:
    received = {}

    def registry(_package=None, **kwargs):
        received.update(kwargs)
        value = Registry()
        value.register_rule(
            FakeRule(id="service.test", category="service", status=status)
        )
        return value

    monkeypatch.setattr("makermedic.cli.create_registry", registry)
    result = runner.invoke(
        app,
        [
            "diagnose",
            "--category",
            "service",
            "--url",
            "http://localhost:8000/health",
            "--json",
        ],
    )
    assert result.exit_code == expected_exit
    assert json.loads(result.stdout)["results"][0]["category"] == "service"
    assert received["service_target"].port == 8000


def test_cli_json_includes_root_cause_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "makermedic.cli.create_registry",
        lambda _package=None, **_kwargs: registry_with_status(DiagnosticStatus.FAIL),
    )
    result = runner.invoke(app, ["diagnose", "--json"])
    payload = json.loads(result.stdout)
    analysis = payload["root_cause_analysis"]
    assert result.exit_code == 1
    assert analysis["actionable_findings"][0]["diagnostic_id"] == "diagnostic.example"
    assert analysis["actionable_findings"][0]["kind"] == "FAILURE"


def test_diagnose_save_round_trip_and_refuses_overwrite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "makermedic.cli.create_registry",
        lambda _package=None, **_kwargs: registry_with_status(DiagnosticStatus.PASS),
    )
    path = tmp_path / "snapshot.json"
    first = runner.invoke(app, ["diagnose", "--save", str(path)])
    second = runner.invoke(app, ["diagnose", "--save", str(path)])
    forced = runner.invoke(app, ["diagnose", "--save", str(path), "--force"])
    assert first.exit_code == 0
    assert "Snapshot saved" in first.stdout
    assert json.loads(path.read_text())["schema_version"] == 1
    assert second.exit_code == 2
    assert "already exists" in second.stderr
    assert forced.exit_code == 0


def test_force_requires_save() -> None:
    result = runner.invoke(app, ["diagnose", "--force"])
    assert result.exit_code == 2
    assert "requires --save" in result.stderr


def _write_cli_snapshot(path: Path, status: str) -> None:
    dependency = "SATISFIED" if status == "PASS" else "UNSATISFIED"
    finding_kind = "FAILURE" if status == "FAIL" else None
    root_findings = (
        [
            {
                "diagnostic_id": "example",
                "category": "test",
                "status": status,
                "dependency_state": dependency,
                "kind": finding_kind,
                "summary": status,
                "affected_diagnostics": [],
                "recommendations": [],
                "evidence_refs": [],
            }
        ]
        if finding_kind
        else []
    )
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": "2026-01-01T00:00:00Z",
                "makermedic_version": "0.1.0",
                "metadata": {
                    "category_filter": "test",
                    "service_url": None,
                    "package": None,
                    "serial_open_test": False,
                },
                "diagnostics": [
                    {
                        "diagnostic_id": "example",
                        "category": "test",
                        "status": status,
                        "dependency_state": dependency,
                        "result_origin": "EVALUATED",
                        "finding_kind": finding_kind,
                        "summary": status,
                        "blocked_by": [],
                        "recommendations": [],
                        "evidence_refs": [],
                    }
                ],
                "root_cause_analysis": {
                    "actionable_findings": root_findings,
                    "unresolved_findings": [],
                    "optional_absences": [],
                    "supporting_findings": [],
                    "blocked_diagnostics": [],
                    "healthy_count": int(status == "PASS"),
                },
            }
        ),
        encoding="utf-8",
    )


def test_compare_and_verify_json_share_comparison_engine(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    _write_cli_snapshot(before, "FAIL")
    _write_cli_snapshot(after, "PASS")
    compared = runner.invoke(app, ["compare", str(before), str(after), "--json"])
    verified = runner.invoke(app, ["verify", str(before), str(after), "--json"])
    assert compared.exit_code == 0
    assert verified.exit_code == 0
    assert (
        json.loads(compared.stdout)["diagnostic_changes"][0]["outcome_change"]
        == "RESOLVED"
    )
    assert json.loads(verified.stdout)["resolved_findings"] == ["example"]


def test_compare_regression_exits_one_and_persistent_failure_does_not(
    tmp_path: Path,
) -> None:
    passed = tmp_path / "passed.json"
    failed = tmp_path / "failed.json"
    _write_cli_snapshot(passed, "PASS")
    _write_cli_snapshot(failed, "FAIL")
    regression = runner.invoke(app, ["compare", str(passed), str(failed)])
    persistent = runner.invoke(app, ["verify", str(failed), str(failed)])
    assert regression.exit_code == 1
    assert persistent.exit_code == 0


def test_compare_invalid_snapshot_is_usage_error(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("not json", encoding="utf-8")
    result = runner.invoke(app, ["compare", str(invalid), str(invalid)])
    assert result.exit_code == 2
    assert "invalid snapshot JSON" in result.stderr
