from __future__ import annotations

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
    def __init__(self, wait=0):
        self.closed = []
        self.wait = wait
        self.terminated = []

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True

    def WaitForSingleObject(self, handle, timeout):
        return self.wait

    def GetExitCodeProcess(self, handle, status):
        status._obj.value = 7
        return True

    def TerminateJobObject(self, job, status):
        self.terminated.append((job, status))
        return True


class _LaunchKernel:
    def __init__(self, failure=None, cleanup_wait_failure=False):
        self.failure = failure
        self.cleanup_wait_failure = cleanup_wait_failure
        self.calls = []
        self.closed = []
        self.created_process = False
        self.terminated_processes = []

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
        if not attributes:
            size._obj.value = 64
            return False
        return True

    def UpdateProcThreadAttribute(self, *args):
        return self._succeeds("UpdateProcThreadAttribute")

    def DeleteProcThreadAttributeList(self, attributes):
        self.calls.append("DeleteProcThreadAttributeList")

    def CreateProcessW(self, *args):
        if not self._succeeds("CreateProcessW"):
            return False
        process = args[-1]._obj
        process.hProcess = 201
        process.hThread = 202
        process.dwProcessId = 203
        self.created_process = True
        return True

    def CreateJobObjectW(self, *args):
        if not self._succeeds("CreateJobObjectW"):
            return 0
        return 301

    def SetInformationJobObject(self, *args):
        return self._succeeds("SetInformationJobObject")

    def AssignProcessToJobObject(self, *args):
        return self._succeeds("AssignProcessToJobObject")

    def ResumeThread(self, *args):
        return 0 if self._succeeds("ResumeThread") else 0xFFFFFFFF

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True

    def TerminateProcess(self, handle, status):
        self.terminated_processes.append((handle, status))
        return True

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
    def configure(kernel):
        monkeypatch.setattr(windows, "_KERNEL32", kernel)
        monkeypatch.setattr(windows, "_is_windows", True)
        monkeypatch.setattr(
            windows,
            "msvcrt",
            SimpleNamespace(get_osfhandle=lambda descriptor: descriptor),
            raising=False,
        )

    return configure


def test_process_closes_job_only_after_parent_is_reaped(monkeypatch):
    kernel = _Kernel()
    monkeypatch.setattr(windows, "_KERNEL32", kernel)
    process = windows._Process(10, 123, 20)

    assert process.wait() == 7
    assert kernel.closed == [10, 20]
    process._conda_mcp_close_job()
    assert kernel.closed == [10, 20]


def test_process_kill_terminates_job_without_closing_it(monkeypatch):
    kernel = _Kernel()
    monkeypatch.setattr(windows, "_KERNEL32", kernel)
    process = windows._Process(10, 123, 20)

    process.kill()

    assert kernel.terminated == [(20, 1)]
    assert kernel.closed == []


def test_process_rejects_wait_failure(monkeypatch):
    monkeypatch.setattr(windows, "_KERNEL32", _Kernel(wait=0xFFFFFFFF))
    process = windows._Process(10, 123, 20)

    with pytest.raises(OSError, match="WaitForSingleObject"):
        process.poll()


def test_process_wait_timeout_keeps_native_handles_open(monkeypatch):
    kernel = _Kernel(wait=258)
    monkeypatch.setattr(windows, "_KERNEL32", kernel)
    process = windows._Process(10, 123, 20)

    with pytest.raises(Exception, match="timed out"):
        process.wait(timeout=0.01)

    assert kernel.closed == []


def test_attribute_list_deletes_initialized_list_when_update_fails(monkeypatch):
    kernel = _AttributeKernel()
    monkeypatch.setattr(windows, "_KERNEL32", kernel)

    with pytest.raises(OSError, match="UpdateProcThreadAttribute"):
        windows._attribute_list([101, 202])

    assert len(kernel.deleted) == 1


def test_launch_assigns_suspended_process_before_resuming_and_reaps_resources(
    portable_windows,
):
    kernel = _LaunchKernel()
    portable_windows(kernel)

    process = launch(
        ["wrapper", "argument"],
        {"_CONDA_MCP_LAUNCH": '{"fixture": true}'},
        10,
        11,
    )

    assert (
        kernel.calls.index("CreateProcessW")
        < kernel.calls.index("SetInformationJobObject")
        < kernel.calls.index("AssignProcessToJobObject")
    )
    assert kernel.calls.index("AssignProcessToJobObject") < kernel.calls.index(
        "ResumeThread"
    )
    assert process.pid == 203
    assert process.wait() == 7
    assert process._handle == 0
    assert process._job == 0
    assert sorted(kernel.closed) == [101, 102, 103, 104, 201, 202, 301]


@pytest.mark.parametrize(
    "failure",
    [
        "SetInformationJobObject",
        "AssignProcessToJobObject",
        "ResumeThread",
        "CreateJobObjectW",
    ],
)
def test_launch_failure_after_process_creation_terminates_and_reaps_process(
    portable_windows, failure
):
    kernel = _LaunchKernel(failure)
    portable_windows(kernel)

    with pytest.raises(Exception, match="Could not create") as error:
        launch(
            ["wrapper"],
            {"_CONDA_MCP_LAUNCH": '{"fixture": true}'},
            10,
            11,
        )

    assert isinstance(error.value.__cause__, OSError)
    assert kernel.terminated_processes == [(201, 1)]
    expected = [101, 102, 103, 104, 201, 202]
    if failure != "CreateJobObjectW":
        expected.append(301)
    assert sorted(kernel.closed) == expected


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

    assert kernel.terminated_processes == []
    assert sorted(kernel.closed) == [101, 102, 103, 104]


def test_launch_preserves_stage_error_when_process_reap_fails(portable_windows):
    kernel = _LaunchKernel("CreateJobObjectW", cleanup_wait_failure=True)
    portable_windows(kernel)

    with pytest.raises(Exception, match="Could not create") as error:
        launch(
            ["wrapper"],
            {"_CONDA_MCP_LAUNCH": '{"fixture": true}'},
            10,
            11,
        )

    assert isinstance(error.value.__cause__, OSError)
    assert error.value.__cause__.strerror == "CreateJobObjectW"
    assert sorted(kernel.closed) == [101, 102, 103, 104, 201, 202]


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
