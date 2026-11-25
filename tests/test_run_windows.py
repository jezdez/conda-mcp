from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from conda_mcp import run as runner


class _Process:
    pid = 123

    def __init__(self, error):
        self.error = error
        self.calls = []

    def kill(self):
        self.calls.append("kill")
        raise self.error

    def _conda_mcp_close_job(self):
        self.calls.append("close")

    def wait(self, timeout):
        assert 0 <= timeout <= 5
        self.calls.append("wait")
        return 1


@pytest.mark.parametrize(
    "error",
    [
        OSError(5, "terminate"),
        KeyboardInterrupt(),
        SystemExit(),
        asyncio.CancelledError(),
    ],
)
def test_windows_reap_closes_job_and_waits_when_termination_fails(monkeypatch, error):
    monkeypatch.setattr(runner, "os", SimpleNamespace(name="nt"))
    process = _Process(error)

    with pytest.raises(type(error)) as caught:
        runner._reap_after_interrupt(process, grace=0.01)

    assert caught.value is error
    assert process.calls == ["kill", "close", "wait"]


def test_windows_reap_preserves_termination_error_when_close_and_wait_fail(monkeypatch):
    monkeypatch.setattr(runner, "os", SimpleNamespace(name="nt"))
    error = OSError(5, "terminate")
    process = _Process(error)

    def close():
        process.calls.append("close")
        raise OSError(6, "private environment value")

    def wait(timeout):
        process.calls.append("wait")
        raise TimeoutError("private command argument")

    monkeypatch.setattr(process, "_conda_mcp_close_job", close)
    monkeypatch.setattr(process, "wait", wait)
    with pytest.raises(OSError) as caught:
        runner._reap_after_interrupt(process, grace=0.01)

    assert caught.value is error
    assert process.calls == ["kill", "close", "wait"]
    assert len(error.__notes__) == 2
    assert "private" not in " ".join(error.__notes__)
    assert "6" in error.__notes__[0]


def test_windows_reap_uses_remaining_cleanup_budget(monkeypatch):
    monkeypatch.setattr(runner, "os", SimpleNamespace(name="nt"))
    clock = iter((100.0, 104.0))
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(clock))
    process = _Process(OSError(5, "terminate"))
    timeouts = []
    monkeypatch.setattr(process, "wait", lambda timeout: timeouts.append(timeout))

    with pytest.raises(OSError):
        runner._reap_after_interrupt(process, grace=0.01)

    assert timeouts == [1.0]


def test_windows_wait_preserves_interruption_and_restores_handlers(monkeypatch):
    monkeypatch.setattr(runner, "os", SimpleNamespace(name="nt"))
    error = KeyboardInterrupt()
    process = _Process(OSError(5, "terminate"))
    restored = []
    old_handler = object()
    monkeypatch.setattr(
        runner.signal,
        "signal",
        lambda sig, handler: restored.append((sig, handler)) or old_handler,
    )

    def poll():
        raise error

    monkeypatch.setattr(process, "poll", poll, raising=False)
    with pytest.raises(KeyboardInterrupt) as caught:
        runner._wait_for_process(process)

    assert caught.value is error
    assert process.calls == ["kill", "close", "wait"]
    assert [handler for _, handler in restored[-2:]] == [old_handler, old_handler]
    assert error.__notes__
