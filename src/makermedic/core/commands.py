"""Small safe subprocess boundary for diagnostic probes."""

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class CommandStatus(StrEnum):
    COMPLETED = "COMPLETED"
    NOT_FOUND = "NOT_FOUND"
    TIMED_OUT = "TIMED_OUT"


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    status: CommandStatus
    return_code: int | None = None
    stdout: str = ""
    stderr: str = ""


class CommandRunner:
    """Execute argument arrays without a shell and with a fixed timeout."""

    def __init__(self, timeout: float = 5.0) -> None:
        self._timeout = timeout

    def run(self, args: Sequence[str]) -> CommandResult:
        command = tuple(args)
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                check=False,
                shell=False,
                text=True,
                timeout=self._timeout,
            )
        except FileNotFoundError:
            return CommandResult(args=command, status=CommandStatus.NOT_FOUND)
        except subprocess.TimeoutExpired as error:
            return CommandResult(
                args=command,
                status=CommandStatus.TIMED_OUT,
                stdout=_as_text(error.stdout),
                stderr=_as_text(error.stderr),
            )
        return CommandResult(
            args=command,
            status=CommandStatus.COMPLETED,
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def _as_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""
