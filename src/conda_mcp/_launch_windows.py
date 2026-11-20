"""Windows process-tree containment for activated launch wrappers."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
from ctypes import wintypes
from typing import Any

from conda import CondaError

_PAYLOAD = "_CONDA_MCP_LAUNCH"
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_CREATE_SUSPENDED = 0x00000004
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_DUPLICATE_SAME_ACCESS = 0x00000002
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_HANDLE_FLAG_INHERIT = 0x00000001
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
_STARTF_USESTDHANDLES = 0x00000100
_STD_INPUT_HANDLE = -10
_STD_OUTPUT_HANDLE = -11
_STD_ERROR_HANDLE = -12
_WAIT_OBJECT_0 = 0
_WAIT_FAILED = 0xFFFFFFFF
_WAIT_TIMEOUT = 258
_is_windows = os.name == "nt"


if _is_windows:
    import msvcrt

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _KERNEL32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _KERNEL32.AssignProcessToJobObject.restype = wintypes.BOOL
    _KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
    _KERNEL32.CloseHandle.restype = wintypes.BOOL
    _KERNEL32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _KERNEL32.CreateFileW.restype = wintypes.HANDLE
    _KERNEL32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPCWSTR,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    _KERNEL32.CreateProcessW.restype = wintypes.BOOL
    _KERNEL32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _KERNEL32.CreateJobObjectW.restype = wintypes.HANDLE
    _KERNEL32.DuplicateHandle.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    _KERNEL32.DuplicateHandle.restype = wintypes.BOOL
    _KERNEL32.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
    _KERNEL32.DeleteProcThreadAttributeList.restype = None
    _KERNEL32.GetCurrentProcess.restype = wintypes.HANDLE
    _KERNEL32.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _KERNEL32.GetExitCodeProcess.restype = wintypes.BOOL
    _KERNEL32.InitializeProcThreadAttributeList.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    _KERNEL32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    _KERNEL32.ResumeThread.argtypes = [wintypes.HANDLE]
    _KERNEL32.ResumeThread.restype = wintypes.DWORD
    _KERNEL32.SetHandleInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    _KERNEL32.SetHandleInformation.restype = wintypes.BOOL
    _KERNEL32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _KERNEL32.SetInformationJobObject.restype = wintypes.BOOL
    _KERNEL32.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
    _KERNEL32.SetStdHandle.restype = wintypes.BOOL
    _KERNEL32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _KERNEL32.TerminateProcess.restype = wintypes.BOOL
    _KERNEL32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _KERNEL32.TerminateJobObject.restype = wintypes.BOOL
    _KERNEL32.UpdateProcThreadAttribute.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.c_size_t,
        wintypes.LPVOID,
        ctypes.c_size_t,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    _KERNEL32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    _KERNEL32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _KERNEL32.WaitForSingleObject.restype = wintypes.DWORD
else:
    _KERNEL32 = None


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPVOID),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
        ("lpAttributeList", wintypes.LPVOID),
    ]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def _kernel32() -> Any:
    """Return the Windows DLL once launch has passed its platform guard."""
    if _KERNEL32 is None:
        raise RuntimeError("Windows launcher is unavailable on this platform.")
    return _KERNEL32


def _protocol_payload(payload: str, stdin_handle: int, stdout_handle: int) -> str:
    """Add raw inheritable protocol handles to the reserved trampoline data."""
    if len(payload.encode()) > 65536:
        raise ValueError("launch payload is too large")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("invalid launch payload")
    if any(
        not isinstance(handle, int) or isinstance(handle, bool) or handle <= 0
        for handle in (stdin_handle, stdout_handle)
    ):
        raise ValueError("invalid protocol handle")
    value["stdin_handle"] = stdin_handle
    value["stdout_handle"] = stdout_handle
    encoded = json.dumps(value, ensure_ascii=False)
    # cmd.exe drops inherited variables longer than 8,191 UTF-16 code units.
    if len(f"{_PAYLOAD}={encoded}".encode("utf-16-le")) // 2 > 8191:
        raise ValueError("Windows launch payload is too large for cmd.exe")
    return encoded


def restore_protocol(payload: dict[str, object]) -> None:
    """Restore the saved protocol CRT descriptors and Windows standard handles."""
    if not _is_windows or _KERNEL32 is None:
        raise CondaError(
            "Windows protocol restoration is unavailable on this platform."
        )
    try:
        stdin_handle = payload["stdin_handle"]
        stdout_handle = payload["stdout_handle"]
    except (KeyError, TypeError, ValueError) as exc:
        raise CondaError("Invalid Windows protocol handles.") from exc
    if any(
        not isinstance(handle, int) or isinstance(handle, bool) or handle <= 0
        for handle in (stdin_handle, stdout_handle)
    ):
        raise CondaError("Invalid Windows protocol handles.")
    for handle, target, standard in (
        (stdin_handle, 0, _STD_INPUT_HANDLE),
        (stdout_handle, 1, _STD_OUTPUT_HANDLE),
    ):
        descriptor = msvcrt.open_osfhandle(handle, os.O_BINARY)
        if descriptor < 0:
            _raise("open_osfhandle")
        try:
            os.dup2(descriptor, target)
        finally:
            if descriptor != target:
                os.close(descriptor)
        if not _kernel32().SetStdHandle(standard, msvcrt.get_osfhandle(target)):
            _raise("SetStdHandle")


class _Process:
    """Small Popen-compatible process owner that closes its job after reaping."""

    def __init__(self, handle: int, pid: int, job: int):
        self._handle = handle
        self._job = job
        self.pid = pid
        self.returncode: int | None = None

    def _conda_mcp_close_job(self) -> None:
        """Close the job handle once, killing any remaining descendants."""
        if self._job:
            _kernel32().CloseHandle(self._job)
            self._job = 0

    def poll(self) -> int | None:
        """Return the exit code if the wrapper has finished."""
        if self.returncode is not None:
            return self.returncode
        result = _kernel32().WaitForSingleObject(self._handle, 0)
        if result == _WAIT_TIMEOUT:
            return None
        if result == _WAIT_FAILED:
            _raise("WaitForSingleObject")
        return self.wait()

    def wait(self, timeout: float | None = None) -> int:
        """Wait for the wrapper and close its process and job handles."""
        if self.returncode is not None:
            return self.returncode
        milliseconds = 0xFFFFFFFF if timeout is None else max(0, int(timeout * 1000))
        result = _kernel32().WaitForSingleObject(self._handle, milliseconds)
        if result == _WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired([], timeout or 0)
        if result == _WAIT_FAILED:
            _raise("WaitForSingleObject")
        status = wintypes.DWORD()
        if not _kernel32().GetExitCodeProcess(self._handle, ctypes.byref(status)):
            _raise("GetExitCodeProcess")
        self.returncode = status.value
        _kernel32().CloseHandle(self._handle)
        self._handle = 0
        self._conda_mcp_close_job()
        return self.returncode

    def kill(self) -> None:
        """Stop every process in the job before the parent reaps the wrapper."""
        if self._job and not _kernel32().TerminateJobObject(self._job, 1):
            _raise("TerminateJobObject")

    terminate = kill


def _raise(operation: str) -> None:
    get_last_error = getattr(ctypes, "get_last_error", lambda: 0)
    raise OSError(get_last_error(), operation)


def _duplicate(handle: int) -> int:
    duplicate = wintypes.HANDLE()
    current = _kernel32().GetCurrentProcess()
    if not _kernel32().DuplicateHandle(
        current,
        handle,
        current,
        ctypes.byref(duplicate),
        0,
        True,
        _DUPLICATE_SAME_ACCESS,
    ):
        _raise("DuplicateHandle")
    return int(duplicate.value or 0)


def _attribute_list(handles: list[int]) -> tuple[object, wintypes.LPVOID, object]:
    size = ctypes.c_size_t()
    _kernel32().InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    buffer = ctypes.create_string_buffer(size.value)
    attributes = ctypes.cast(buffer, wintypes.LPVOID)
    if not _kernel32().InitializeProcThreadAttributeList(
        attributes, 1, 0, ctypes.byref(size)
    ):
        _raise("InitializeProcThreadAttributeList")
    try:
        values = (wintypes.HANDLE * len(handles))(*handles)
        if not _kernel32().UpdateProcThreadAttribute(
            attributes,
            0,
            _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            values,
            ctypes.sizeof(values),
            None,
            None,
        ):
            _raise("UpdateProcThreadAttribute")
    except BaseException:
        _kernel32().DeleteProcThreadAttributeList(attributes)
        raise
    return buffer, attributes, values


def launch(
    command: list[str], environment: dict[str, str], stdin_fd: int, stdout_fd: int
) -> _Process:
    """Start an activated wrapper suspended and assign it to a kill-on-close job."""
    if not _is_windows or _KERNEL32 is None:
        raise CondaError("Windows launcher is unavailable on this platform.")
    handles: list[int] = []
    attributes: wintypes.LPVOID | None = None
    process = _ProcessInformation()
    job = 0
    try:
        protocol_stdin = _duplicate(msvcrt.get_osfhandle(stdin_fd))
        handles.append(protocol_stdin)
        protocol_stdout = _duplicate(msvcrt.get_osfhandle(stdout_fd))
        handles.append(protocol_stdout)
        diagnostic = _duplicate(msvcrt.get_osfhandle(2))
        handles.append(diagnostic)
        null = _kernel32().CreateFileW(
            "NUL", 0x80000000, 0x3, None, 3, _FILE_ATTRIBUTE_NORMAL, None
        )
        if null == _INVALID_HANDLE_VALUE:
            _raise("CreateFileW")
        handles.append(null)
        if not _kernel32().SetHandleInformation(
            null, _HANDLE_FLAG_INHERIT, _HANDLE_FLAG_INHERIT
        ):
            _raise("SetHandleInformation")
        environment = environment.copy()
        if any("\0" in key or "\0" in value for key, value in environment.items()):
            raise ValueError("environment contains NUL")
        environment[_PAYLOAD] = _protocol_payload(
            environment[_PAYLOAD], protocol_stdin, protocol_stdout
        )
        attributes_buffer, attributes, handle_values = _attribute_list(handles)
        startup = _StartupInfo()
        startup.cb = ctypes.sizeof(startup)
        startup.dwFlags = _STARTF_USESTDHANDLES
        startup.hStdInput, startup.hStdOutput, startup.hStdError = (
            null,
            diagnostic,
            diagnostic,
        )
        startup.lpAttributeList = attributes
        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        environment_block = ctypes.create_unicode_buffer(
            "\0".join(f"{key}={value}" for key, value in environment.items()) + "\0\0"
        )
        if not _kernel32().CreateProcessW(
            None,
            command_line,
            None,
            None,
            True,
            _CREATE_SUSPENDED
            | _CREATE_UNICODE_ENVIRONMENT
            | _EXTENDED_STARTUPINFO_PRESENT,
            environment_block,
            None,
            ctypes.byref(startup),
            ctypes.byref(process),
        ):
            _raise("CreateProcessW")
        job = _kernel32().CreateJobObjectW(None, None)
        if not job:
            _raise("CreateJobObjectW")
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _kernel32().SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            _raise("SetInformationJobObject")
        if not _kernel32().AssignProcessToJobObject(job, process.hProcess):
            _raise("AssignProcessToJobObject")
        if _kernel32().ResumeThread(process.hThread) == 0xFFFFFFFF:
            _raise("ResumeThread")
        _kernel32().CloseHandle(process.hThread)
        process.hThread = 0
        return _Process(process.hProcess, process.dwProcessId, job)
    except (KeyError, OSError, ValueError) as exc:
        if process.hThread:
            _kernel32().CloseHandle(process.hThread)
            process.hThread = 0
        if process.hProcess:
            try:
                _kernel32().TerminateProcess(process.hProcess, 1)
                if (
                    _kernel32().WaitForSingleObject(process.hProcess, 5000)
                    != _WAIT_OBJECT_0
                ):
                    _raise("WaitForSingleObject")
            except OSError:
                pass
            _kernel32().CloseHandle(process.hProcess)
            process.hProcess = 0
        if job:
            _kernel32().CloseHandle(job)
        raise CondaError("Could not create contained Windows launch process.") from exc
    finally:
        if attributes:
            _kernel32().DeleteProcThreadAttributeList(attributes)
        for handle in handles:
            _kernel32().CloseHandle(handle)
