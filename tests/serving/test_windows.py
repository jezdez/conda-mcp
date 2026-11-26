from __future__ import annotations

import ctypes

import pytest

from conda_mcp.serving import windows


class _Job:
    def __init__(self, failure: OSError | None = None) -> None:
        self.failure = failure
        self.assigned: list[int] = []

    def assign_process(self, handle: int) -> None:
        self.assigned.append(handle)
        if self.failure:
            raise self.failure


@pytest.fixture
def process_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[str], list[tuple[int, bool, int]]]:
    calls: list[str] = []
    opened: list[tuple[int, bool, int]] = []

    def open_process(access: int, inherit: bool, pid: int) -> int:
        opened.append((access, inherit, pid))
        return 101

    monkeypatch.setattr(windows, "_open_process", open_process)
    monkeypatch.setattr(
        windows, "_close_handle", lambda handle: calls.append(f"close:{handle}")
    )
    monkeypatch.setattr(windows, "_open_process_thread", lambda pid: 202)
    monkeypatch.setattr(
        windows, "_resume_thread", lambda thread: calls.append(f"resume:{thread}") or 0
    )
    return calls, opened


def test_assign_and_resume_assigns_the_process_before_resuming_its_thread(
    monkeypatch: pytest.MonkeyPatch,
    process_bindings: tuple[list[str], list[tuple[int, bool, int]]],
) -> None:
    job = _Job()
    monkeypatch.setattr(windows, "_SharedWindowsJob", lambda: job)
    owner = windows.WindowsJob()

    owner.assign_and_resume(42)

    calls, opened = process_bindings
    assert job.assigned == [101]
    assert opened == [
        (windows._PROCESS_SET_QUOTA | windows._PROCESS_TERMINATE, False, 42)
    ]
    assert calls == ["close:101", "resume:202", "close:202"]


def test_assignment_failure_does_not_resume_the_suspended_process(
    monkeypatch: pytest.MonkeyPatch,
    process_bindings: tuple[list[str], list[tuple[int, bool, int]]],
) -> None:
    monkeypatch.setattr(
        windows, "_SharedWindowsJob", lambda: _Job(OSError(5, "access denied"))
    )
    owner = windows.WindowsJob()

    with pytest.raises(OSError, match="access denied"):
        owner.assign_and_resume(42)

    assert process_bindings[0] == ["close:101"]


def test_resume_error_propagates_without_reinterpreting_process_state(
    monkeypatch: pytest.MonkeyPatch,
    process_bindings: tuple[list[str], list[tuple[int, bool, int]]],
) -> None:
    monkeypatch.setattr(
        windows, "_resume_thread", lambda thread: windows._RESUME_FAILED
    )
    monkeypatch.setattr(windows, "_SharedWindowsJob", _Job)
    owner = windows.WindowsJob()

    with pytest.raises(OSError, match="ResumeThread"):
        owner.assign_and_resume(42)

    assert process_bindings[0] == ["close:101", "close:202"]


def test_process_open_failure_never_assigns_or_resumes(monkeypatch, process_bindings):
    job = _Job()
    monkeypatch.setattr(windows, "_SharedWindowsJob", lambda: job)
    monkeypatch.setattr(windows, "_open_process", lambda *args: None)
    with pytest.raises(OSError, match="OpenProcess"):
        windows.WindowsJob().assign_and_resume(42)
    assert job.assigned == []
    assert process_bindings[0] == []


def test_failed_thread_snapshot_is_not_closed_as_a_valid_handle(monkeypatch):
    closed = []
    monkeypatch.setattr(
        windows, "_create_snapshot", lambda *args: windows._INVALID_HANDLE_VALUE
    )
    monkeypatch.setattr(windows, "_close_handle", closed.append)
    with pytest.raises(OSError, match="CreateToolhelp32Snapshot"):
        windows._open_process_thread(42)
    assert closed == []


@pytest.mark.parametrize("matching_thread", [False, True])
def test_thread_lookup_failure_closes_the_snapshot(monkeypatch, matching_thread):
    closed = []
    monkeypatch.setattr(windows, "_create_snapshot", lambda *args: 303)

    def first(snapshot, pointer):
        entry = ctypes.cast(pointer, ctypes.POINTER(windows._ThreadEntry)).contents
        entry.th32OwnerProcessID = 42
        entry.th32ThreadID = 7
        return matching_thread

    monkeypatch.setattr(windows, "_thread_first", first)
    monkeypatch.setattr(windows, "_open_thread", lambda *args: None)
    monkeypatch.setattr(windows, "_close_handle", closed.append)
    with pytest.raises(
        OSError, match="OpenThread" if matching_thread else "no thread found"
    ):
        windows._open_process_thread(42)
    assert closed == [303]
