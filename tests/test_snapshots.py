import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from makermedic.core.errors import (
    SnapshotDecodeError,
    SnapshotExistsError,
    SnapshotNotFoundError,
    SnapshotValidationError,
    UnsupportedSnapshotVersionError,
)
from makermedic.core.models import (
    DiagnosticResult,
    DiagnosticRun,
    DiagnosticStatus,
    RootCauseAnalysis,
)
from makermedic.core.snapshots import (
    DiagnosticSnapshot,
    load_snapshot,
    save_snapshot,
    snapshot_from_run,
)


def sample_snapshot() -> DiagnosticSnapshot:
    run = DiagnosticRun(
        timestamp=datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        evidence=(),
        probe_outcomes=(),
        results=(
            DiagnosticResult(
                diagnostic_id="gpu.driver",
                category="gpu",
                status=DiagnosticStatus.FAIL,
                summary="Driver failed",
                evidence=("gpu.driver.available",),
                recommendations=("Review driver.",),
            ),
        ),
        root_cause_analysis=RootCauseAnalysis(healthy_count=0),
    )
    return snapshot_from_run(run, category_filter="gpu")


def test_snapshot_content_is_conservative_and_versioned() -> None:
    snapshot = sample_snapshot()
    assert snapshot.schema_version == 1
    assert snapshot.metadata.category_filter == "gpu"
    assert snapshot.diagnostics[0].evidence_refs == ("gpu.driver.available",)
    payload = snapshot.model_dump(mode="json")
    assert "evidence" not in payload
    assert "probe_outcomes" not in payload


def test_atomic_save_utf8_round_trip(tmp_path: Path) -> None:
    destination = tmp_path / "snapshot.json"
    snapshot = sample_snapshot()
    save_snapshot(snapshot, destination)
    assert json.loads(destination.read_text(encoding="utf-8"))["schema_version"] == 1
    assert load_snapshot(destination) == snapshot
    assert list(tmp_path.glob("*.tmp")) == []


def test_existing_destination_refused_and_force_overwrites(tmp_path: Path) -> None:
    destination = tmp_path / "snapshot.json"
    destination.write_text("original", encoding="utf-8")
    with pytest.raises(SnapshotExistsError):
        save_snapshot(sample_snapshot(), destination)
    assert destination.read_text(encoding="utf-8") == "original"
    save_snapshot(sample_snapshot(), destination, force=True)
    assert load_snapshot(destination).schema_version == 1


def test_serialization_failure_leaves_no_destination_or_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args, **_kwargs):
        raise RuntimeError("serialization failed")

    monkeypatch.setattr(DiagnosticSnapshot, "model_dump_json", fail)
    destination = tmp_path / "snapshot.json"
    with pytest.raises(RuntimeError, match="serialization failed"):
        save_snapshot(sample_snapshot(), destination)
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


def test_missing_snapshot() -> None:
    with pytest.raises(SnapshotNotFoundError):
        load_snapshot(Path("/definitely/missing/snapshot.json"))


@pytest.mark.parametrize("content", ["{", b"\xff"])
def test_malformed_json_or_utf8(tmp_path: Path, content) -> None:
    path = tmp_path / "bad.json"
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    with pytest.raises(SnapshotDecodeError):
        load_snapshot(path)


@pytest.mark.parametrize("payload", [[], {"diagnostics": []}])
def test_wrong_top_level_or_missing_version(tmp_path: Path, payload) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SnapshotValidationError):
        load_snapshot(path)


def test_unsupported_future_version(tmp_path: Path) -> None:
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")
    with pytest.raises(UnsupportedSnapshotVersionError):
        load_snapshot(path)


def test_invalid_diagnostic_model(tmp_path: Path) -> None:
    payload = sample_snapshot().model_dump(mode="json")
    payload["diagnostics"][0]["status"] = "EXPLODE"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SnapshotValidationError):
        load_snapshot(path)


def test_unknown_fields_and_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    payload = sample_snapshot().model_dump(mode="json")
    payload["unexpected"] = True
    path = tmp_path / "extra.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SnapshotValidationError):
        load_snapshot(path)

    payload.pop("unexpected")
    payload["diagnostics"].append(payload["diagnostics"][0])
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SnapshotValidationError, match="duplicate diagnostic IDs"):
        load_snapshot(path)


def test_malicious_looking_strings_remain_inert_data(tmp_path: Path) -> None:
    payload = sample_snapshot().model_dump(mode="json")
    payload["diagnostics"][0]["summary"] = "__import__('os').system('touch owned')"
    path = tmp_path / "inert.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_snapshot(path)
    assert loaded.diagnostics[0].summary.startswith("__import__")
    assert not tmp_path.joinpath("owned").exists()
