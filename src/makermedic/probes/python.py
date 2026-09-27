"""Python runtime, pip, and installed-package fact collection."""

import importlib.metadata
import os
import re
import shutil
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from makermedic.core.commands import CommandResult, CommandRunner, CommandStatus
from makermedic.core.models import Evidence, EvidenceAvailability

_PIP_VERSION = re.compile(
    r"^pip (?P<version>\S+) from (?P<location>.+?) \(python .+\)$"
)


@dataclass(frozen=True)
class PythonRuntime:
    version: str
    version_info: tuple[int, int, int]
    implementation: str
    executable: str
    prefix: str
    base_prefix: str
    real_prefix: str | None = None


class PythonEnvironmentProbe:
    id = "python.environment"
    categories = ("python",)

    def __init__(
        self,
        runtime: PythonRuntime | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._runtime = runtime or current_runtime()
        self._environment = environment if environment is not None else os.environ

    def collect(self) -> Iterable[Evidence]:
        runtime = self._runtime
        in_virtualenv = (
            runtime.prefix != runtime.base_prefix or runtime.real_prefix is not None
        )
        environment_type = _environment_type(in_virtualenv, runtime, self._environment)
        return (
            Evidence(key="python.version", source=self.id, value=runtime.version),
            Evidence(
                key="python.version_info",
                source=self.id,
                value=list(runtime.version_info),
            ),
            Evidence(
                key="python.implementation",
                source=self.id,
                value=runtime.implementation,
            ),
            Evidence(key="python.executable", source=self.id, value=runtime.executable),
            Evidence(key="python.prefix", source=self.id, value=runtime.prefix),
            Evidence(
                key="python.base_prefix", source=self.id, value=runtime.base_prefix
            ),
            Evidence(key="python.in_virtualenv", source=self.id, value=in_virtualenv),
            Evidence(key="python.venv.type", source=self.id, value=environment_type),
        )


class PipProbe:
    """Inspect both interpreter-bound pip and the shell's PATH pip."""

    id = "python.pip"
    categories = ("python",)

    def __init__(
        self,
        *,
        python_executable: str | None = None,
        which: Callable[[str], str | None] = shutil.which,
        runner: CommandRunner | None = None,
    ) -> None:
        self._python_executable = python_executable or sys.executable
        self._which = which
        self._runner = runner or CommandRunner()

    def collect(self) -> Iterable[Evidence]:
        source = self.id
        module_result = self._runner.run(
            (self._python_executable, "-m", "pip", "--version")
        )
        path_command = self._which("pip")
        path_result = (
            self._runner.run((path_command, "--version")) if path_command else None
        )
        module = _pip_observation(module_result)
        path = _pip_observation(path_result) if path_result else PipObservation(False)
        return (
            _optional_fact("python.pip.module.available", source, module.available),
            _optional_fact("python.pip.module.version", source, module.version),
            _optional_fact("python.pip.module.location", source, module.location),
            Evidence(key="python.pip.path.command", source=source, value=path_command),
            _optional_fact("python.pip.path.available", source, path.available),
            _optional_fact("python.pip.path.version", source, path.version),
            _optional_fact("python.pip.path.location", source, path.location),
        )


class PackageMetadataProbe:
    """Inspect distribution metadata without importing the requested package."""

    id = "python.package"
    categories = ("python",)

    def __init__(
        self,
        package: str,
        distribution: Callable[[str], importlib.metadata.Distribution] = (
            importlib.metadata.distribution
        ),
    ) -> None:
        self._package = package
        self._distribution = distribution

    def collect(self) -> Iterable[Evidence]:
        try:
            distribution = self._distribution(self._package)
        except importlib.metadata.PackageNotFoundError:
            installed = False
            version = None
            location = None
        else:
            installed = True
            version = distribution.version
            location = _metadata_location(distribution)
        return (
            Evidence(
                key="python.package.requested", source=self.id, value=self._package
            ),
            Evidence(key="python.package.installed", source=self.id, value=installed),
            Evidence(key="python.package.version", source=self.id, value=version),
            Evidence(
                key="python.package.metadata_location",
                source=self.id,
                value=location,
            ),
        )


def current_runtime() -> PythonRuntime:
    return PythonRuntime(
        version=sys.version.split()[0],
        version_info=(
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        ),
        implementation=sys.implementation.name,
        executable=sys.executable,
        prefix=sys.prefix,
        base_prefix=sys.base_prefix,
        real_prefix=getattr(sys, "real_prefix", None),
    )


def _environment_type(
    in_virtualenv: bool,
    runtime: PythonRuntime,
    environment: Mapping[str, str],
) -> str:
    if not in_virtualenv:
        return "none"
    if environment.get("CONDA_PREFIX"):
        return "conda"
    if runtime.real_prefix is not None:
        return "virtualenv"
    if (
        Path(runtime.prefix, "pyvenv.cfg").is_file()
        or runtime.prefix != runtime.base_prefix
    ):
        return "venv"
    return "unknown"


@dataclass(frozen=True)
class PipObservation:
    available: bool | None
    version: str | None = None
    location: str | None = None


def _pip_observation(result: CommandResult) -> PipObservation:
    if result.status is not CommandStatus.COMPLETED:
        return PipObservation(None)
    if result.return_code != 0:
        return PipObservation(False)
    match = _PIP_VERSION.fullmatch(result.stdout.strip())
    if match is None:
        return PipObservation(None)
    return PipObservation(True, match.group("version"), match.group("location"))


def _optional_fact(key: str, source: str, value: object | None) -> Evidence:
    if value is None:
        return Evidence(
            key=key,
            source=source,
            availability=EvidenceAvailability.UNAVAILABLE,
        )
    return Evidence(key=key, source=source, value=value)


def _metadata_location(distribution: importlib.metadata.Distribution) -> str | None:
    for file in distribution.files or ():
        if file.name in {"METADATA", "PKG-INFO"}:
            return str(distribution.locate_file(file))
    return None
