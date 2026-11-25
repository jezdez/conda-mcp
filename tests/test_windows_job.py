from __future__ import annotations

from types import SimpleNamespace

import pytest
from conda.common.compat import on_win

from conda_mcp import _windows_job


class _Handle:
    def __init__(self, value: int) -> None:
        self.value = value

    def __int__(self) -> int:
        return self.value

    def Close(self) -> None:
        self.bindings.close(self)


class _Pywin32Error(Exception):
    def __init__(self, code: int, operation: str, detail: str) -> None:
        super().__init__(code, operation, detail)
        self.winerror = code


class _Bindings:
    def __init__(self) -> None:
        self.closed: list[_Handle] = []
        self.assigned: list[tuple[_Handle, int]] = []
        self.terminated: list[tuple[_Handle, int]] = []
        self.fail: dict[str, BaseException] = {}
        self.info = {
            "BasicLimitInformation": {
                "PerProcessUserTimeLimit": 1,
                "PerJobUserTimeLimit": 2,
                "LimitFlags": 4,
                "MinimumWorkingSetSize": 5,
                "MaximumWorkingSetSize": 6,
                "ActiveProcessLimit": 7,
                "Affinity": 8,
                "PriorityClass": 9,
                "SchedulingClass": 10,
            },
            "IoInfo": {
                "ReadOperationCount": 11,
                "WriteOperationCount": 12,
                "OtherOperationCount": 13,
                "ReadTransferCount": 14,
                "WriteTransferCount": 15,
                "OtherTransferCount": 16,
            },
            "ProcessMemoryLimit": 17,
            "JobMemoryLimit": 18,
            "PeakProcessMemoryUsed": 19,
            "PeakJobMemoryUsed": 20,
        }

    def _raise(self, operation: str) -> None:
        if error := self.fail.get(operation):
            raise error

    def create(self, security: None, name: None) -> _Handle:
        self._raise("CreateJobObject")
        assert security is None
        assert name is None
        handle = _Handle(101)
        handle.bindings = self
        return handle

    def query(self, handle: _Handle, information_class: int) -> dict[str, object]:
        self._raise("QueryInformationJobObject")
        assert handle.value == 101
        assert information_class == 9
        return self.info

    def configure(self, handle: _Handle, information_class: int, value: object) -> None:
        self._raise("SetInformationJobObject")
        assert handle.value == 101
        assert information_class == 9
        assert value is self.info
        basic = value["BasicLimitInformation"]
        assert isinstance(basic, dict)
        assert basic["LimitFlags"] == 0x2004
        assert set(value) == {
            "BasicLimitInformation",
            "IoInfo",
            "ProcessMemoryLimit",
            "JobMemoryLimit",
            "PeakProcessMemoryUsed",
            "PeakJobMemoryUsed",
        }

    def assign(self, handle: _Handle, process: int) -> None:
        self._raise("AssignProcessToJobObject")
        self.assigned.append((handle, process))

    def terminate(self, handle: _Handle, status: int) -> None:
        self._raise("TerminateJobObject")
        self.terminated.append((handle, status))

    def close(self, handle: _Handle) -> None:
        self._raise("CloseHandle")
        self.closed.append(handle)


@pytest.fixture
def bindings(monkeypatch: pytest.MonkeyPatch):
    value = _Bindings()
    monkeypatch.setattr(_windows_job, "on_win", True)
    monkeypatch.setattr(
        _windows_job.sys,
        "getwindowsversion",
        lambda: SimpleNamespace(major=10),
        raising=False,
    )
    monkeypatch.setattr(
        _windows_job,
        "pywintypes",
        type(
            "Types",
            (),
            {"error": _Pywin32Error, "HANDLE": staticmethod(lambda raw: raw)},
        ),
    )
    monkeypatch.setattr(_windows_job, "_create_job", value.create, raising=False)
    monkeypatch.setattr(
        _windows_job,
        "_close_handle",
        lambda raw: value.close(raw) or True,
        raising=False,
    )
    monkeypatch.setattr(
        _windows_job,
        "win32job",
        type(
            "Job",
            (),
            {
                "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE": 0x2000,
                "JobObjectExtendedLimitInformation": 9,
                "CreateJobObject": value.create,
                "QueryInformationJobObject": value.query,
                "SetInformationJobObject": value.configure,
                "AssignProcessToJobObject": value.assign,
                "TerminateJobObject": value.terminate,
            },
        ),
    )
    return value


def test_job_creation_does_not_pass_null_name_through_pywin32(bindings, monkeypatch):
    def reject_null_name(security, name):
        raise TypeError("None is not a valid string in this context")

    monkeypatch.setattr(_windows_job.win32job, "CreateJobObject", reject_null_name)
    job = _windows_job.WindowsJob()
    assert job.handle == 101
    job.close()


@pytest.mark.skipif(not on_win, reason="native Windows jobs")
def test_native_jobs_are_distinct_and_non_inheritable():
    import win32api
    import win32con
    import win32job

    first = _windows_job.WindowsJob()
    try:
        second = _windows_job.WindowsJob()
        try:
            assert first.handle != second.handle
            assert (
                not win32api.GetHandleInformation(first.handle)
                & win32con.HANDLE_FLAG_INHERIT
            )
            info = win32job.QueryInformationJobObject(
                first.handle, win32job.JobObjectExtendedLimitInformation
            )
            info["BasicLimitInformation"]["LimitFlags"] |= (
                win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            )
            info["BasicLimitInformation"]["ActiveProcessLimit"] = 1
            win32job.SetInformationJobObject(
                first.handle, win32job.JobObjectExtendedLimitInformation, info
            )
            other = win32job.QueryInformationJobObject(
                second.handle, win32job.JobObjectExtendedLimitInformation
            )
            assert (
                not other["BasicLimitInformation"]["LimitFlags"]
                & win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            )
        finally:
            second.close()
    finally:
        first.close()


def test_windows_job_configures_kill_on_close_and_borrows_process_handle(
    bindings: _Bindings,
) -> None:
    job = _windows_job.WindowsJob()

    assert job.handle == 101
    job.assign_process(202)
    job.terminate()
    job.close()

    assert [(handle.value, process) for handle, process in bindings.assigned] == [
        (101, 202)
    ]
    assert [(handle.value, status) for handle, status in bindings.terminated] == [
        (101, 1)
    ]
    assert [handle.value for handle in bindings.closed] == [101]


def test_windows_job_handle_is_unavailable_after_close(bindings: _Bindings) -> None:
    job = _windows_job.WindowsJob()

    job.close()
    job.close()
    job.terminate()

    with pytest.raises(RuntimeError, match="closed"):
        _ = job.handle
    assert len(bindings.closed) == 1
    assert bindings.terminated == []


def test_windows_job_preserves_ownership_when_close_fails(bindings: _Bindings) -> None:
    job = _windows_job.WindowsJob()
    bindings.fail["CloseHandle"] = _Pywin32Error(6, "CloseHandle", "invalid handle")

    with pytest.raises(OSError, match="CloseHandle"):
        job.close()

    assert job.handle == 101


@pytest.mark.parametrize(
    ("operation", "action"),
    [
        ("AssignProcessToJobObject", lambda job: job.assign_process(202)),
        ("TerminateJobObject", lambda job: job.terminate()),
        ("CloseHandle", lambda job: job.close()),
    ],
)
def test_windows_job_translates_pywin32_errors(
    bindings: _Bindings, operation: str, action: object
) -> None:
    job = _windows_job.WindowsJob()
    bindings.fail[operation] = _Pywin32Error(5, operation, "access denied")

    with pytest.raises(OSError, match=operation) as error:
        action(job)  # type: ignore[operator]

    assert error.value.errno == 5


def test_configuration_failure_closes_acquired_job_and_preserves_primary_error(
    bindings: _Bindings,
) -> None:
    bindings.fail["SetInformationJobObject"] = _Pywin32Error(
        5, "SetInformationJobObject", "access denied"
    )
    bindings.fail["CloseHandle"] = _Pywin32Error(6, "CloseHandle", "invalid handle")

    with pytest.raises(OSError, match="SetInformationJobObject") as error:
        _windows_job.WindowsJob()

    assert error.value.errno == 5
    assert error.value.__notes__ == ["CloseHandle cleanup failed: OSError: code=6"]


def test_query_failure_preserves_its_native_operation_and_cleanup_failure(
    bindings: _Bindings,
) -> None:
    bindings.fail["QueryInformationJobObject"] = _Pywin32Error(
        87, "QueryInformationJobObject", "invalid parameter"
    )
    bindings.fail["CloseHandle"] = KeyboardInterrupt()

    with pytest.raises(OSError, match="QueryInformationJobObject") as error:
        _windows_job.WindowsJob()

    assert error.value.errno == 87
    assert error.value.__notes__ == ["CloseHandle cleanup failed: KeyboardInterrupt"]


def test_query_interruption_closes_the_acquired_job(bindings: _Bindings) -> None:
    bindings.fail["QueryInformationJobObject"] = KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        _windows_job.WindowsJob()

    assert [handle.value for handle in bindings.closed] == [101]


def test_missing_pywin32_explains_how_to_enable_windows_containment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_windows_job, "on_win", True)
    monkeypatch.setattr(
        _windows_job.sys,
        "getwindowsversion",
        lambda: SimpleNamespace(major=10),
        raising=False,
    )
    monkeypatch.setattr(_windows_job, "pywintypes", None)
    monkeypatch.setattr(_windows_job, "win32job", None)

    with pytest.raises(RuntimeError, match="pywin32>=311"):
        _windows_job.WindowsJob()


def test_pre_windows_10_is_rejected_before_creating_a_job(
    bindings: _Bindings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        _windows_job.sys,
        "getwindowsversion",
        lambda: SimpleNamespace(major=6),
    )

    with pytest.raises(RuntimeError, match="Windows 10 or Server 2016"):
        _windows_job.WindowsJob()


def test_interruption_during_configuration_closes_the_acquired_job(
    bindings: _Bindings,
) -> None:
    bindings.fail["SetInformationJobObject"] = KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        _windows_job.WindowsJob()

    assert [handle.value for handle in bindings.closed] == [101]


def test_configuration_error_survives_system_exit_from_cleanup(
    bindings: _Bindings,
) -> None:
    bindings.fail["SetInformationJobObject"] = _Pywin32Error(
        5, "SetInformationJobObject", "access denied"
    )
    bindings.fail["CloseHandle"] = SystemExit("secret")

    with pytest.raises(OSError, match="SetInformationJobObject") as error:
        _windows_job.WindowsJob()

    assert error.value.errno == 5
    assert error.value.__notes__ == ["CloseHandle cleanup failed: SystemExit"]
    assert "secret" not in error.value.__notes__[0]


def test_create_failure_does_not_close_an_unowned_handle(bindings, monkeypatch) -> None:
    monkeypatch.setattr(_windows_job, "_create_job", lambda *_: 0)
    monkeypatch.setattr(_windows_job.ctypes, "get_last_error", lambda: 5, raising=False)

    with pytest.raises(OSError, match="CreateJobObject") as error:
        _windows_job.WindowsJob()

    assert error.value.errno == 5
    assert bindings.closed == []


def test_handle_adoption_failure_closes_raw_job(bindings, monkeypatch):
    error = MemoryError("handle allocation")

    def fail(raw):
        raise error

    monkeypatch.setattr(_windows_job.pywintypes, "HANDLE", fail)
    with pytest.raises(MemoryError) as caught:
        _windows_job.WindowsJob()
    assert caught.value is error
    assert [int(handle) for handle in bindings.closed] == [101]


def test_handle_adoption_failure_preserves_error_when_raw_close_fails(
    bindings, monkeypatch
):
    error = MemoryError("handle allocation")

    def fail(raw):
        raise error

    monkeypatch.setattr(_windows_job.pywintypes, "HANDLE", fail)
    monkeypatch.setattr(_windows_job, "_close_handle", lambda raw: False)
    monkeypatch.setattr(_windows_job.ctypes, "get_last_error", lambda: 6, raising=False)
    with pytest.raises(MemoryError) as caught:
        _windows_job.WindowsJob()
    assert caught.value is error
    assert error.__notes__ == ["CloseHandle cleanup failed: OSError: code=6"]
