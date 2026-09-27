"""Portable, privacy-conservative diagnostic snapshots and JSON persistence."""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from makermedic import __version__
from makermedic.core.errors import (
    SnapshotDecodeError,
    SnapshotExistsError,
    SnapshotNotFoundError,
    SnapshotValidationError,
    SnapshotWriteError,
    UnsupportedSnapshotVersionError,
)
from makermedic.core.models import (
    DependencyState,
    DiagnosticRun,
    DiagnosticStatus,
    FindingKind,
    ResultOrigin,
    RootCauseAnalysis,
)

SNAPSHOT_SCHEMA_VERSION = 1


class SnapshotMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    category_filter: str | None = None
    service_url: str | None = None
    package: str | None = None
    serial_open_test: bool = False


class SnapshotDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    diagnostic_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    status: DiagnosticStatus
    dependency_state: DependencyState
    result_origin: ResultOrigin
    finding_kind: FindingKind | None = None
    summary: str = Field(min_length=1)
    blocked_by: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


class DiagnosticSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int
    created_at: datetime
    makermedic_version: str = Field(min_length=1)
    metadata: SnapshotMetadata
    diagnostics: tuple[SnapshotDiagnostic, ...]
    root_cause_analysis: RootCauseAnalysis | None = None

    @model_validator(mode="after")
    def diagnostic_ids_are_unique(self) -> "DiagnosticSnapshot":
        identifiers = [item.diagnostic_id for item in self.diagnostics]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("snapshot contains duplicate diagnostic IDs")
        return self


def snapshot_from_run(
    run: DiagnosticRun,
    *,
    category_filter: str | None = None,
    service_url: str | None = None,
    package: str | None = None,
    serial_open_test: bool = False,
) -> DiagnosticSnapshot:
    """Create a portable snapshot without copying evidence values."""
    return DiagnosticSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        created_at=run.timestamp,
        makermedic_version=__version__,
        metadata=SnapshotMetadata(
            category_filter=category_filter,
            service_url=service_url,
            package=package,
            serial_open_test=serial_open_test,
        ),
        diagnostics=tuple(
            SnapshotDiagnostic(
                diagnostic_id=result.diagnostic_id,
                category=result.category,
                status=result.status,
                dependency_state=result.dependency_state,
                result_origin=result.origin,
                finding_kind=result.finding_kind,
                summary=result.summary,
                blocked_by=result.blocked_by,
                recommendations=result.recommendations,
                evidence_refs=result.evidence,
            )
            for result in run.results
        ),
        root_cause_analysis=run.root_cause_analysis,
    )


def save_snapshot(
    snapshot: DiagnosticSnapshot, path: Path, *, force: bool = False
) -> None:
    """Atomically save UTF-8 JSON, refusing replacement unless explicitly forced."""
    destination = path.expanduser()
    if destination.exists() and not force:
        raise SnapshotExistsError(f"snapshot already exists: {destination}")
    payload = snapshot.model_dump_json(indent=2) + "\n"
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
    except OSError as error:
        raise SnapshotWriteError(f"could not create snapshot: {destination}") from error
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if force:
            os.replace(temporary, destination)
        else:
            try:
                os.link(temporary, destination)
            except FileExistsError as error:
                raise SnapshotExistsError(
                    f"snapshot already exists: {destination}"
                ) from error
            temporary.unlink()
    except SnapshotExistsError:
        temporary.unlink(missing_ok=True)
        raise
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise SnapshotWriteError(f"could not write snapshot: {destination}") from error
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def load_snapshot(path: Path) -> DiagnosticSnapshot:
    """Load and validate untrusted snapshot JSON without executing its contents."""
    source = path.expanduser()
    try:
        text = source.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise SnapshotNotFoundError(f"snapshot not found: {source}") from error
    except (OSError, UnicodeError) as error:
        raise SnapshotDecodeError(f"could not read snapshot: {source}") from error
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise SnapshotDecodeError(f"invalid snapshot JSON: {source}") from error
    if not isinstance(payload, dict):
        raise SnapshotValidationError("snapshot top level must be a JSON object")
    if "schema_version" not in payload:
        raise SnapshotValidationError("snapshot schema_version is required")
    version = payload["schema_version"]
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != SNAPSHOT_SCHEMA_VERSION
    ):
        raise UnsupportedSnapshotVersionError(
            f"unsupported snapshot schema version: {version!r}"
        )
    try:
        return DiagnosticSnapshot.model_validate(payload)
    except ValidationError as error:
        raise SnapshotValidationError(f"invalid snapshot structure: {error}") from error
