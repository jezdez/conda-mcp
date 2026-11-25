from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace

import pytest

from conda_mcp import _launch_windows as windows
from conda_mcp._launch_windows import _protocol_payload, launch, restore_protocol


class _AttributeKernel:
    def __init__(self):
        self.deleted = []

    def InitializeProcThreadAttributeList(self, attributes, count, flags, size):
        if not attributes:
            size._obj.value = 64
            return False
        return True

    def UpdateProcThreadAttribute(self, *args):
        return False

    def DeleteProcThreadAttributeList(self, attributes):
        self.deleted.append(attributes)


class _ArrayAllocationFailure:
    def __mul__(self, count):
        raise MemoryError("array allocation")


class _SecondArrayAllocationFailure:
    def __init__(self):
        self.count = 0

    def __mul__(self, count):
        self.count += 1
        if self.count == 2:
            raise MemoryError("job array allocation")
        return __import__("ctypes").c_void_p * count


class _TwoAttributeKernel(_AttributeKernel):
    def __init__(self, *, sizing_error=122, failure_at=None):
        super().__init__()
        self.sizing_error = sizing_error
        self.failure_at = failure_at
        self.updates = []

    def InitializeProcThreadAttributeList(self, attributes, count, flags, size):
        assert count == 2
        if not attributes:
            size._obj.value = 64
            return False
        return True

    def UpdateProcThreadAttribute(
        self, attributes, flags, attribute, value, size, previous, returned
    ):
        self.updates.append((attribute, value, size))
        return len(self.updates) != self.failure_at


def test_protocol_payload_includes_raw_windows_handles():
    value = _protocol_payload('{"argv": ["server"], "fixture": true}', 101, 202)

    assert json.loads(value) == {
        "argv": ["server"],
        "fixture": True,
        "stdin_handle": 101,
        "stdout_handle": 202,
    }


def test_protocol_payload_rejects_invalid_reserved_data():
    with pytest.raises(ValueError, match="invalid launch payload"):
        _protocol_payload("[]", 101, 202)


@pytest.mark.parametrize("handle", [True, "101", 0, -1])
def test_protocol_payload_rejects_invalid_raw_handles(handle):
    with pytest.raises(ValueError, match="invalid protocol handle"):
        _protocol_payload('{"argv": ["server"]}', handle, 202)


def test_protocol_payload_preserves_its_size_limit():
    with pytest.raises(ValueError, match="too large"):
        _protocol_payload("x" * 65537, 101, 202)


@pytest.mark.parametrize("argument", ["x", "\U0001f600"])
def test_protocol_payload_fits_the_cmd_environment_limit(argument):
    overhead = (
        len(
            (
                windows._PAYLOAD + "=" + _protocol_payload('{"argv": [""]}', 101, 202)
            ).encode("utf-16-le")
        )
        // 2
    )
    count = (8191 - overhead) // (len(argument.encode("utf-16-le")) // 2)
    payload = json.dumps({"argv": [argument * count]}, ensure_ascii=False)
    assert json.loads(_protocol_payload(payload, 101, 202))["argv"] == [
        argument * count
    ]
    oversized = json.dumps({"argv": [argument * (count + 1)]}, ensure_ascii=False)
    with pytest.raises(ValueError, match="too large"):
        _protocol_payload(oversized, 101, 202)


class _Kernel:
    def __init__(self, wait=0, close_failures=()):
        self.closed = []
        self.wait = wait
        self.terminated = []
        self.close_failures = set(close_failures)

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return handle not in self.close_failures

    def WaitForSingleObject(self, handle, timeout):
        return self.wait

    def GetExitCodeProcess(self, handle, status):
        status._obj.value = 7
        return True


class _Job:
    def __init__(self, handle=20, *, failure=None):
        self.handle = handle
        self.failure = failure
        self.assigned = []
        self.terminated = 0
        self.closed = 0

    def assign_process(self, handle):
        if self.failure == "assign":
            raise OSError(5, "AssignProcessToJobObject")
        self.assigned.append(handle)

    def terminate(self):
        self.terminated += 1
        if self.failure == "terminate":
            raise OSError(5, "TerminateJobObject")
        if self.failure == "terminate-control-flow":
            raise KeyboardInterrupt()

    def close(self):
        self.closed += 1
        if self.failure == "close":
            raise OSError(6, "CloseHandle")
        if self.failure == "close-control-flow":
            raise SystemExit()


class _IdentityError(Exception):
    pass


class _LaunchKernel:
    def __init__(self, failure=None, cleanup_wait_failure=False, close_failures=()):
        self.failure = failure
        self.cleanup_wait_failure = cleanup_wait_failure
        self.calls = []
        self.closed = []
        self.created_process = False
        self.terminated_processes = []
        self.close_failures = set(close_failures)

    def _succeeds(self, name):
        self.calls.append(name)
        return self.failure != name

    def GetCurrentProcess(self):
        return 1

    def DuplicateHandle(
        self, current, handle, target, duplicate, access, inherit, flags
    ):
        if not self._succeeds("DuplicateHandle"):
            return False
        duplicate._obj.value = 100 + len(
            [call for call in self.calls if call == "DuplicateHandle"]
        )
        return True

    def CreateFileW(self, *args):
        if not self._succeeds("CreateFileW"):
            return windows._INVALID_HANDLE_VALUE
        return 104

    def SetHandleInformation(self, *args):
        return self._succeeds("SetHandleInformation")

    def InitializeProcThreadAttributeList(self, attributes, count, flags, size):
        self.calls.append("InitializeProcThreadAttributeList")
        assert count == 2
        if not attributes:
            size._obj.value = 64
            return False
        return True

    def UpdateProcThreadAttribute(self, *args):
        return self._succeeds("UpdateProcThreadAttribute")

    def DeleteProcThreadAttributeList(self, attributes):
        self.calls.append("DeleteProcThreadAttributeList")
        if self.failure == "DeleteProcThreadAttributeList":
            raise OSError(8, "DeleteProcThreadAttributeList")

    def CreateProcessW(self, *args):
        if not self._succeeds("CreateProcessW"):
            return False
        process = args[-1]._obj
        process.hProcess = 201
        process.hThread = 202
        process.dwProcessId = 203
        self.created_process = True
        return True

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return handle not in self.close_failures

    def WaitForSingleObject(self, handle, timeout):
        self.calls.append("WaitForSingleObject")
        if self.cleanup_wait_failure:
            return windows._WAIT_FAILED
        return 0

    def GetExitCodeProcess(self, handle, status):
        status._obj.value = 7
        return True


@pytest.fixture
def portable_windows(monkeypatch):
    def configure(kernel, job=None):
        monkeypatch.setattr(windows, "_KERNEL32", kernel)
        monkeypatch.setattr(windows, "_is_windows", True)
        monkeypatch.setattr(
            windows,
            "msvcrt",
            SimpleNamespace(get_osfhandle=lambda descriptor: descriptor),
            raising=False,
        )
        value = job or _Job(handle=301)
        monkeypatch.setattr(windows, "WindowsJob", lambda: value)
        monkeypatch.setattr(windows, "_last_error", lambda: 122)
        return value

    return configure


def test_process_closes_job_only_after_parent_is_reaped(monkeypatch):
    kernel = _Kernel()
    monkeypatch.setattr(windows, "_KERNEL32", kernel)
    job = _Job()
    process = windows._Process(10, 123, job)

    assert process.wait() == 7
    assert kernel.closed == [10]
    assert job.closed == 1
    process._conda_mcp_close_job()
    assert job.closed == 1


def test_process_kill_terminates_job_without_closing_it(monkeypatch):
    kernel = _Kernel()
    monkeypatch.setattr(windows, "_KERNEL32", kernel)
    job = _Job()
    process = windows._Process(10, 123, job)

    process.kill()

    assert job.terminated == 1
    assert kernel.closed == []


def test_process_rejects_wait_failure(monkeypatch):
    monkeypatch.setattr(windows, "_KERNEL32", _Kernel(wait=0xFFFFFFFF))
    process = windows._Process(10, 123, _Job())

    with pytest.raises(OSError, match="WaitForSingleObject"):
        process.poll()


def test_process_wait_timeout_keeps_native_handles_open(monkeypatch):
    kernel = _Kernel(wait=258)
    monkeypatch.setattr(windows, "_KERNEL32", kernel)
    process = windows._Process(10, 123, _Job())

    with pytest.raises(Exception, match="timed out"):
        process.wait(timeout=0.01)

    assert kernel.closed == []


def test_attribute_list_deletes_initialized_list_when_update_fails(monkeypatch):
    kernel = _AttributeKernel()
    monkeypatch.setattr(windows, "_KERNEL32", kernel)
    monkeypatch.setattr(windows, "_last_error", lambda: 122)

    with pytest.raises(OSError, match="UpdateProcThreadAttribute"):
        windows._attribute_list([101, 202], 303)

    assert len(kernel.deleted) == 1


def test_attribute_list_sets_handle_and_job_attributes_and_keeps_arrays_alive(
    monkeypatch,
):
    kernel = _TwoAttributeKernel()
    monkeypatch.setattr(windows, "_KERNEL32", kernel)
    monkeypatch.setattr(windows, "_last_error", lambda: kernel.sizing_error)

    resources = windows._attribute_list([101, 202], 303)

    assert [update[0] for update in kernel.updates] == [
        windows._PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
        windows._PROC_THREAD_ATTRIBUTE_JOB_LIST,
    ]
    assert [int(handle) for handle in resources.handle_values] == [101, 202]
    assert [int(handle) for handle in resources.job_values] == [303]
    resources.close()
    assert len(kernel.deleted) == 1


@pytest.mark.parametrize("failure_at", [1, 2])
def test_attribute_list_deletes_initialized_list_for_each_update_failure(
    monkeypatch, failure_at
):
    kernel = _TwoAttributeKernel(failure_at=failure_at)
    monkeypatch.setattr(windows, "_KERNEL32", kernel)
    monkeypatch.setattr(windows, "_last_error", lambda: kernel.sizing_error)

    with pytest.raises(OSError, match="UpdateProcThreadAttribute"):
        windows._attribute_list([101, 202], 303)

    assert len(kernel.deleted) == 1


@pytest.mark.parametrize("sizing_error, size", [(0, 64), (5, 64), (122, 0)])
def test_attribute_list_rejects_invalid_sizing_result(monkeypatch, sizing_error, size):
    kernel = _TwoAttributeKernel(sizing_error=sizing_error)
    original = kernel.InitializeProcThreadAttributeList

    def initialize(attributes, count, flags, result_size):
        result = original(attributes, count, flags, result_size)
        if not attributes:
            result_size._obj.value = size
        return result

    kernel.InitializeProcThreadAttributeList = initialize
    monkeypatch.setattr(windows, "_KERNEL32", kernel)
    monkeypatch.setattr(windows, "_last_error", lambda: kernel.sizing_error)

    with pytest.raises(OSError, match="InitializeProcThreadAttributeList"):
        windows._attribute_list([101, 202], 303)

    assert kernel.deleted == []


def test_attribute_list_releases_initialized_list_when_handle_array_allocation_fails(
    monkeypatch,
):
    kernel = _TwoAttributeKernel()
    monkeypatch.setattr(windows, "_KERNEL32", kernel)
    monkeypatch.setattr(windows, "_last_error", lambda: 122)
    monkeypatch.setattr(windows.wintypes, "HANDLE", _ArrayAllocationFailure())

    with pytest.raises(MemoryError, match="array allocation"):
        windows._attribute_list([101, 202], 303)

    assert len(kernel.deleted) == 1


def test_attribute_list_releases_initialized_list_when_job_array_allocation_fails(
    monkeypatch,
):
    kernel = _TwoAttributeKernel()
    monkeypatch.setattr(windows, "_KERNEL32", kernel)
    monkeypatch.setattr(windows, "_last_error", lambda: 122)
    monkeypatch.setattr(windows.wintypes, "HANDLE", _SecondArrayAllocationFailure())

    with pytest.raises(MemoryError, match="job array allocation"):
        windows._attribute_list([101, 202], 303)

    assert len(kernel.deleted) == 1


def test_attribute_list_marks_delete_complete_before_interruption(monkeypatch):
    kernel = _TwoAttributeKernel()
    monkeypatch.setattr(windows, "_KERNEL32", kernel)
    monkeypatch.setattr(windows, "_last_error", lambda: 122)
    attributes = windows._attribute_list([101, 202], 303)

    def interrupt(value):
        kernel.deleted.append(value)
        raise _IdentityError()

    monkeypatch.setattr(kernel, "DeleteProcThreadAttributeList", interrupt)
    with pytest.raises(_IdentityError):
        attributes.close()
    attributes.close()

    assert len(kernel.deleted) == 1


def test_launch_creates_process_with_job_attribute_and_reaps_resources(
    portable_windows,
):
    kernel = _LaunchKernel()
    job = portable_windows(kernel)

    process = launch(
        ["wrapper", "argument"],
        {"_CONDA_MCP_LAUNCH": '{"fixture": true}'},
        10,
        11,
    )

    assert job.assigned == []
    assert process.pid == 203
    assert process.wait() == 7
    assert process._handle == 0
    assert process._job is None
    assert job.closed == 1
    assert sorted(kernel.closed) == [101, 102, 103, 104, 201, 202]


def test_launch_thread_close_failure_terminates_job_and_reaps_process(
    portable_windows,
):
    kernel = _LaunchKernel(close_failures={202})
    job = portable_windows(kernel)

    with pytest.raises(Exception, match="Could not create") as error:
        launch(
            ["wrapper"],
            {"_CONDA_MCP_LAUNCH": '{"fixture": true}'},
            10,
            11,
        )

    assert isinstance(error.value.__cause__, OSError)
    assert job.terminated == 1
    assert job.closed == 1
    assert sorted(kernel.closed) == [101, 102, 103, 104, 201, 202, 202]


@pytest.mark.parametrize(
    "failure",
    [
        "SetHandleInformation",
        "UpdateProcThreadAttribute",
        "CreateProcessW",
    ],
)
def test_launch_failure_before_assignment_releases_acquired_handles(
    portable_windows, failure
):
    kernel = _LaunchKernel(failure)
    portable_windows(kernel)

    with pytest.raises(Exception, match="Could not create"):
        launch(
            ["wrapper"],
            {"_CONDA_MCP_LAUNCH": '{"fixture": true}'},
            10,
            11,
        )

    assert sorted(kernel.closed) == [101, 102, 103, 104]


def test_launch_preserves_stage_error_when_process_reap_fails(portable_windows):
    kernel = _LaunchKernel(cleanup_wait_failure=True, close_failures={202})
    job = portable_windows(kernel)

    with pytest.raises(Exception, match="Could not create") as error:
        launch(
            ["wrapper"],
            {"_CONDA_MCP_LAUNCH": '{"fixture": true}'},
            10,
            11,
        )

    assert isinstance(error.value.__cause__, OSError)
    assert error.value.__cause__.strerror == "CloseHandle"
    assert sorted(kernel.closed) == [101, 102, 103, 104, 201, 202, 202]
    assert job.terminated == 1
    assert job.closed == 1


@pytest.mark.parametrize(
    "error",
    [asyncio.CancelledError(), KeyboardInterrupt(), SystemExit()],
)
def test_launch_preserves_control_flow_error_after_cleanup(
    portable_windows, monkeypatch, error
):
    kernel = _LaunchKernel()
    job = portable_windows(kernel)

    def close(handle):
        kernel.closed.append(handle)
        if handle == 202:
            raise error
        return True

    monkeypatch.setattr(kernel, "CloseHandle", close)

    with pytest.raises(type(error)) as raised:
        launch(["wrapper"], {"_CONDA_MCP_LAUNCH": '{"fixture": true}'}, 10, 11)

    assert raised.value is error
    assert job.terminated == 1
    assert job.closed == 1
    assert sorted(kernel.closed) == [101, 102, 103, 104, 201, 202, 202]


def test_launch_termination_failure_still_closes_and_reaps(portable_windows):
    kernel = _LaunchKernel(close_failures={202})
    job = portable_windows(kernel, _Job(failure="terminate"))

    with pytest.raises(Exception, match="Could not create") as error:
        launch(["wrapper"], {"_CONDA_MCP_LAUNCH": '{"fixture": true}'}, 10, 11)

    assert job.terminated == 1
    assert job.closed == 1
    assert any("TerminateJobObject" in note for note in error.value.__notes__)
    assert kernel.calls.count("WaitForSingleObject") == 1


def test_launch_reap_timeout_is_explicitly_noted(portable_windows):
    kernel = _LaunchKernel(close_failures={202})
    kernel.WaitForSingleObject = lambda handle, timeout: windows._WAIT_TIMEOUT
    portable_windows(kernel)

    with pytest.raises(Exception, match="Could not create") as error:
        launch(["wrapper"], {"_CONDA_MCP_LAUNCH": '{"fixture": true}'}, 10, 11)

    assert any("TimeoutError" in note for note in error.value.__notes__)


def test_launch_duplicate_close_failure_cleans_all_resources_before_transfer(
    portable_windows,
):
    kernel = _LaunchKernel(close_failures={101})
    job = portable_windows(kernel)

    with pytest.raises(Exception, match="Could not create"):
        launch(["wrapper"], {"_CONDA_MCP_LAUNCH": '{"fixture": true}'}, 10, 11)

    assert job.terminated == 1
    assert job.closed == 1
    assert sorted(kernel.closed) == [101, 101, 102, 103, 104, 201, 202]


def test_launch_cleanup_note_includes_native_operation_and_code(portable_windows):
    kernel = _LaunchKernel(close_failures={202})
    portable_windows(kernel, _Job(failure="terminate"))

    with pytest.raises(Exception, match="Could not create") as error:
        launch(["wrapper"], {"_CONDA_MCP_LAUNCH": '{"fixture": true}'}, 10, 11)

    assert any(
        "TerminateJobObject" in note and "5" in note for note in error.value.__notes__
    )


def test_launch_cleanup_note_excludes_native_error_text(portable_windows):
    kernel = _LaunchKernel(close_failures={202})
    job = _Job(failure="terminate")

    def terminate():
        job.terminated += 1
        raise OSError(5, "secret command and environment")

    job.terminate = terminate
    portable_windows(kernel, job)

    with pytest.raises(Exception, match="Could not create") as error:
        launch(["wrapper"], {"_CONDA_MCP_LAUNCH": '{"fixture": true}'}, 10, 11)

    notes = "\n".join(error.value.__notes__)
    assert "TerminateJobObject" in notes
    assert "5" in notes
    assert "OSError" in notes
    assert "secret command and environment" not in notes


def test_launch_cleanup_continues_after_attribute_delete_fails(portable_windows):
    kernel = _LaunchKernel("DeleteProcThreadAttributeList", close_failures={202})
    job = portable_windows(kernel)

    with pytest.raises(Exception, match="Could not create") as error:
        launch(["wrapper"], {"_CONDA_MCP_LAUNCH": '{"fixture": true}'}, 10, 11)

    assert job.terminated == 1
    assert job.closed == 1
    assert sorted(kernel.closed) == [101, 102, 103, 104, 201, 202, 202]
    assert any(
        "DeleteProcThreadAttributeList" in note for note in error.value.__notes__
    )


@pytest.mark.parametrize("failure", ["terminate-control-flow", "close-control-flow"])
def test_launch_cleanup_continues_after_job_control_flow_error(
    portable_windows, failure
):
    kernel = _LaunchKernel(close_failures={202})
    job = portable_windows(kernel, _Job(failure=failure))

    with pytest.raises(Exception, match="Could not create"):
        launch(["wrapper"], {"_CONDA_MCP_LAUNCH": '{"fixture": true}'}, 10, 11)

    assert job.terminated == 1
    assert job.closed == 1
    assert sorted(kernel.closed) == [101, 102, 103, 104, 201, 202, 202]


def test_launch_wraps_shared_job_runtime_error(portable_windows, monkeypatch):
    kernel = _LaunchKernel()
    portable_windows(kernel)
    problem = RuntimeError("Windows job containment requires pywin32>=311")
    monkeypatch.setattr(windows, "WindowsJob", lambda: (_ for _ in ()).throw(problem))

    with pytest.raises(Exception, match="Could not create") as error:
        launch(["wrapper"], {"_CONDA_MCP_LAUNCH": '{"fixture": true}'}, 10, 11)

    assert error.value.__cause__ is problem


def test_launch_constructor_failure_releases_transferred_resources(
    portable_windows, monkeypatch
):
    kernel = _LaunchKernel()
    job = portable_windows(kernel)
    problem = RuntimeError("process owner transfer failed")
    monkeypatch.setattr(
        windows,
        "_Process",
        lambda handle, pid, owner: (_ for _ in ()).throw(problem),
    )

    with pytest.raises(Exception, match="Could not create") as error:
        launch(["wrapper"], {"_CONDA_MCP_LAUNCH": '{"fixture": true}'}, 10, 11)

    assert error.value.__cause__ is problem
    assert job.terminated == 1
    assert job.closed == 1
    assert sorted(kernel.closed) == [101, 102, 103, 104, 201, 202]


@pytest.mark.parametrize("failure", ["process", "job"])
def test_process_wait_retries_close_failures(monkeypatch, failure):
    kernel = _Kernel(close_failures={10} if failure == "process" else ())
    monkeypatch.setattr(windows, "_KERNEL32", kernel)
    job = _Job(failure="close" if failure == "job" else None)
    process = windows._Process(10, 123, job)

    with pytest.raises(OSError, match="CloseHandle"):
        process.wait()

    assert process.returncode == 7
    assert process._handle == (10 if failure == "process" else 0)
    assert process._job is (None if failure == "process" else job)
    kernel.close_failures.clear()
    job.failure = None
    assert process.wait() == 7
    assert process._handle == 0
    assert process._job is None


def test_process_wait_notes_job_close_when_process_close_also_fails(monkeypatch):
    kernel = _Kernel(close_failures={10})
    monkeypatch.setattr(windows, "_KERNEL32", kernel)
    process = windows._Process(10, 123, _Job(failure="close"))

    with pytest.raises(OSError, match="CloseHandle") as error:
        process.wait()

    assert any("CloseHandle(job)" in note for note in error.value.__notes__)
    assert process._handle == 10
    assert process._job is not None


def test_restore_protocol_is_unavailable_off_windows():
    if os.name != "nt":
        with pytest.raises(Exception, match="unavailable"):
            restore_protocol({"stdin_handle": 101, "stdout_handle": 202})


@pytest.mark.skipif(os.name != "nt", reason="Windows native launcher")
def test_windows_kernel32_binding_is_available():
    assert windows._KERNEL32 is not None
    assert callable(windows._KERNEL32.CreateProcessW)


@pytest.mark.skipif(os.name != "nt", reason="Windows native launcher")
def test_launch_runs_a_named_fixture_with_a_contained_process(tmp_path):
    fixture = os.path.join(
        os.path.dirname(__file__), "fixtures", "windows_launch_wrapper.py"
    )
    output = tmp_path / "wrapper-ran"
    stdin, writer = os.pipe()
    reader, stdout = os.pipe()
    os.write(writer, b"in\n")
    os.close(writer)
    process = launch(
        [os.sys.executable, fixture],
        os.environ
        | {
            "WINDOWS_LAUNCH_OUTPUT": str(output),
            "_CONDA_MCP_LAUNCH": '{"fixture": true}',
        },
        stdin,
        stdout,
    )
    try:
        assert process.wait(timeout=5) == 0
        assert output.read_text(encoding="utf-8") == "in\n"
        assert os.read(reader, 3) == b"out"
        assert process._handle == 0
        assert process._job == 0
    finally:
        process._conda_mcp_close_job()
        os.close(stdin)
        os.close(stdout)
        os.close(reader)
