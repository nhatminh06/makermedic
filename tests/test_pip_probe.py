from collections.abc import Sequence

from makermedic.core.commands import CommandResult, CommandStatus
from makermedic.probes.python import PipProbe


class FakeRunner:
    def __init__(self, results: list[CommandResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, ...]] = []

    def run(self, args: Sequence[str]) -> CommandResult:
        self.calls.append(tuple(args))
        return self.results.pop(0)


def completed(output: str, return_code: int = 0) -> CommandResult:
    return CommandResult(
        args=("command",),
        status=CommandStatus.COMPLETED,
        return_code=return_code,
        stdout=output,
    )


def collect(probe: PipProbe) -> dict[str, object]:
    return {item.key: item.value for item in probe.collect()}


def test_python_bound_and_path_pip_are_detected() -> None:
    runner = FakeRunner(
        [
            completed("pip 24.0 from /venv/site-packages/pip (python 3.12)\n"),
            completed("pip 24.0 from /venv/site-packages/pip (python 3.12)\n"),
        ]
    )
    probe = PipProbe(
        python_executable="/venv/bin/python",
        which=lambda _name: "/venv/bin/pip",
        runner=runner,  # type: ignore[arg-type]
    )

    values = collect(probe)

    assert values["python.pip.module.available"] is True
    assert values["python.pip.module.version"] == "24.0"
    assert values["python.pip.path.available"] is True
    assert runner.calls[0] == ("/venv/bin/python", "-m", "pip", "--version")


def test_path_command_absence_is_valid_evidence() -> None:
    runner = FakeRunner(
        [completed("pip 24.0 from /venv/site-packages/pip (python 3.12)\n")]
    )
    values = collect(
        PipProbe(
            python_executable="python",
            which=lambda _name: None,
            runner=runner,  # type: ignore[arg-type]
        )
    )

    assert values["python.pip.path.command"] is None
    assert values["python.pip.path.available"] is False


def test_malformed_pip_output_is_unavailable_without_guessing() -> None:
    runner = FakeRunner([completed("unexpected output"), completed("also malformed")])
    evidence = {
        item.key: item
        for item in PipProbe(
            python_executable="python",
            which=lambda _name: "pip",
            runner=runner,  # type: ignore[arg-type]
        ).collect()
    }

    assert evidence["python.pip.module.available"].availability.value == "UNAVAILABLE"
    assert evidence["python.pip.path.available"].availability.value == "UNAVAILABLE"


def test_nonzero_pip_result_means_pip_is_absent() -> None:
    runner = FakeRunner([completed("No module named pip", return_code=1)])
    values = collect(
        PipProbe(
            python_executable="python",
            which=lambda _name: None,
            runner=runner,  # type: ignore[arg-type]
        )
    )

    assert values["python.pip.module.available"] is False


def test_command_not_found_result_becomes_unavailable() -> None:
    runner = FakeRunner(
        [CommandResult(args=("python",), status=CommandStatus.NOT_FOUND)]
    )
    evidence = {
        item.key: item
        for item in PipProbe(
            python_executable="python",
            which=lambda _name: None,
            runner=runner,  # type: ignore[arg-type]
        ).collect()
    }

    assert evidence["python.pip.module.available"].availability.value == "UNAVAILABLE"


def test_command_timeout_result_becomes_unavailable() -> None:
    runner = FakeRunner(
        [CommandResult(args=("python",), status=CommandStatus.TIMED_OUT)]
    )
    evidence = {
        item.key: item
        for item in PipProbe(
            python_executable="python",
            which=lambda _name: None,
            runner=runner,  # type: ignore[arg-type]
        ).collect()
    }

    assert evidence["python.pip.module.available"].availability.value == "UNAVAILABLE"
