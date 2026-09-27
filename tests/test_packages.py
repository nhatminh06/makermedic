import importlib.metadata
import sys
from pathlib import PurePosixPath

from makermedic.probes.python import PackageMetadataProbe


class FakeDistribution:
    version = "1.2.3"
    files = (PurePosixPath("demo-1.2.3.dist-info/METADATA"),)

    def locate_file(self, path: PurePosixPath) -> PurePosixPath:
        return PurePosixPath("/env/site-packages") / path


def test_installed_package_metadata_is_collected_without_importing() -> None:
    package = "maker_test_package_that_must_not_be_imported"
    assert package not in sys.modules
    probe = PackageMetadataProbe(
        package,
        distribution=lambda _name: FakeDistribution(),  # type: ignore[arg-type,return-value]
    )

    values = {item.key: item.value for item in probe.collect()}

    assert values["python.package.installed"] is True
    assert values["python.package.version"] == "1.2.3"
    assert values["python.package.metadata_location"].endswith("METADATA")
    assert package not in sys.modules


def test_missing_package_is_explicit() -> None:
    def missing(name: str) -> importlib.metadata.Distribution:
        raise importlib.metadata.PackageNotFoundError(name)

    values = {
        item.key: item.value
        for item in PackageMetadataProbe("definitely-missing", missing).collect()
    }

    assert values["python.package.requested"] == "definitely-missing"
    assert values["python.package.installed"] is False
    assert values["python.package.version"] is None
