import subprocess

import pytest

from makermedic.core.commands import CommandRunner, CommandStatus


def test_command_runner_uses_safe_subprocess_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(
        args: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        assert args == ("tool", "--version")
        assert kwargs["shell"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["timeout"] == 2.0
        return subprocess.CompletedProcess(args, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = CommandRunner(timeout=2.0).run(("tool", "--version"))

    assert result.status is CommandStatus.COMPLETED
    assert result.return_code == 0


def test_command_not_found_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    def not_found(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", not_found)

    assert CommandRunner().run(("missing",)).status is CommandStatus.NOT_FOUND


def test_command_timeout_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(("slow",), 1, output=b"partial")

    monkeypatch.setattr(subprocess, "run", timeout)

    result = CommandRunner(timeout=1).run(("slow",))
    assert result.status is CommandStatus.TIMED_OUT
    assert result.stdout == "partial"
