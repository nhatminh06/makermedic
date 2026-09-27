"""Explicit errors at core architecture boundaries."""


class MakerMedicError(Exception):
    """Base class for expected MakerMedic operational errors."""


class ProbeCollectionError(MakerMedicError):
    """A probe expectedly could not perform its intended collection."""


class DiagnosticEvaluationError(MakerMedicError):
    """A rule could not evaluate its intended diagnostic."""


class DuplicateEvidenceError(MakerMedicError):
    """An evidence key is already present in a store."""


class DuplicateRegistrationError(MakerMedicError):
    """A component ID is already registered for its component type."""


class UnknownCategoryError(MakerMedicError):
    """A requested category has no registered probe or rule."""


class MissingDiagnosticDependencyError(MakerMedicError):
    """A diagnostic dependency references an unregistered diagnostic ID."""


class DiagnosticDependencyCycleError(MakerMedicError):
    """Diagnostic dependencies contain a cycle."""


class DuplicateDiagnosticDependencyError(MakerMedicError):
    """A rule declares the same dependency more than once."""


class SnapshotError(MakerMedicError):
    """Base class for snapshot persistence and validation errors."""


class SnapshotNotFoundError(SnapshotError):
    """A requested snapshot file does not exist."""


class SnapshotDecodeError(SnapshotError):
    """A snapshot is not valid UTF-8 JSON."""


class UnsupportedSnapshotVersionError(SnapshotError):
    """A snapshot uses an unsupported schema version."""


class SnapshotValidationError(SnapshotError):
    """Snapshot JSON does not conform to the supported schema."""


class SnapshotExistsError(SnapshotError):
    """A snapshot destination already exists."""


class SnapshotWriteError(SnapshotError):
    """A snapshot could not be written safely."""


class SnapshotTargetMismatchError(SnapshotError):
    """Service snapshots refer to different target identities."""


class BundleError(MakerMedicError):
    """Base class for support-bundle planning and persistence errors."""


class BundleBuildError(BundleError):
    """A support bundle could not be constructed from its source."""


class BundleOutputExistsError(BundleError):
    """A support-bundle destination already exists."""


class BundleWriteError(BundleError):
    """A support bundle could not be written safely."""


class LabError(MakerMedicError):
    """Base class for expected diagnostic-laboratory errors."""


class UnknownScenarioError(LabError):
    """A requested built-in laboratory scenario does not exist."""
