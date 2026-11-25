"""Windows process-tree containment for activated launch wrappers."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

from conda import CondaError

from ._windows_job import WindowsJob

_PAYLOAD = "_CONDA_MCP_LAUNCH"
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_DUPLICATE_SAME_ACCESS = 0x00000002
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_HANDLE_FLAG_INHERIT = 0x00000001
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
_PROC_THREAD_ATTRIBUTE_JOB_LIST = 0x0002000D
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
    _KERNEL32.SetHandleInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    _KERNEL32.SetHandleInformation.restype = wintypes.BOOL
    _KERNEL32.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
    _KERNEL32.SetStdHandle.restype = wintypes.BOOL
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
    if (
        not isinstance(stdin_handle, int)
        or isinstance(stdin_handle, bool)
        or stdin_handle <= 0
        or not isinstance(stdout_handle, int)
        or isinstance(stdout_handle, bool)
        or stdout_handle <= 0
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

    def __init__(self, handle: int, pid: int, job: WindowsJob):
        self._handle = handle
        self._job = job
        self.pid = pid
        self.returncode: int | None = None

    def _conda_mcp_close_job(self) -> None:
        """Close the job handle once, killing any remaining descendants."""
        if self._job is not None:
            self._job.close()
            self._job = None

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
        if self.returncode is not None and not self._handle and self._job is None:
            return self.returncode
        milliseconds = 0xFFFFFFFF if timeout is None else max(0, int(timeout * 1000))
        if self.returncode is None:
            result = _kernel32().WaitForSingleObject(self._handle, milliseconds)
            if result == _WAIT_TIMEOUT:
                raise subprocess.TimeoutExpired([], timeout or 0)
            if result == _WAIT_FAILED:
                _raise("WaitForSingleObject")
            status = wintypes.DWORD()
            if not _kernel32().GetExitCodeProcess(self._handle, ctypes.byref(status)):
                _raise("GetExitCodeProcess")
            self.returncode = status.value
        errors: list[tuple[str, BaseException]] = []
        if self._handle:
            if _close_handle(self._handle, errors):
                self._handle = 0
        try:
            self._conda_mcp_close_job()
        except BaseException as error:
            errors.append(("CloseHandle(job)", error))
        if errors:
            _, error = errors[0]
            for cleanup_operation, cleanup in errors[1:]:
                error.add_note(_cleanup_note(cleanup_operation, cleanup))
            raise error
        return self.returncode

    def kill(self) -> None:
        """Stop every process in the job before the parent reaps the wrapper."""
        if self._job is not None:
            self._job.terminate()

    terminate = kill


def _raise(operation: str) -> None:
    raise OSError(_last_error(), operation)


def _last_error() -> int:
    return getattr(ctypes, "get_last_error", lambda: 0)()


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


@dataclass
class _AttributeList:
    buffer: object
    attributes: wintypes.LPVOID
    handle_values: object
    job_values: object
    _closed: bool = False

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            _kernel32().DeleteProcThreadAttributeList(self.attributes)


def _attribute_list(handles: list[int], job_handle: int) -> _AttributeList:
    size = ctypes.c_size_t()
    initialized = _kernel32().InitializeProcThreadAttributeList(
        None, 2, 0, ctypes.byref(size)
    )
    if initialized or _last_error() != 122 or not size.value:
        _raise("InitializeProcThreadAttributeList")
    buffer = ctypes.create_string_buffer(size.value)
    attributes = ctypes.cast(buffer, wintypes.LPVOID)
    if not _kernel32().InitializeProcThreadAttributeList(
        attributes, 2, 0, ctypes.byref(size)
    ):
        _raise("InitializeProcThreadAttributeList")
    try:
        values = (wintypes.HANDLE * len(handles))(*handles)
        job_values = (wintypes.HANDLE * 1)(job_handle)
        result = _AttributeList(buffer, attributes, values, job_values)
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
        if not _kernel32().UpdateProcThreadAttribute(
            attributes,
            0,
            _PROC_THREAD_ATTRIBUTE_JOB_LIST,
            job_values,
            ctypes.sizeof(job_values),
            None,
            None,
        ):
            _raise("UpdateProcThreadAttribute")
    except BaseException as error:
        try:
            _kernel32().DeleteProcThreadAttributeList(attributes)
        except BaseException as cleanup:
            error.add_note(_cleanup_note("DeleteProcThreadAttributeList", cleanup))
        raise
    return result


def _close_handle(handle: int, errors: list[tuple[str, BaseException]]) -> bool:
    if handle:
        try:
            if not _kernel32().CloseHandle(handle):
                _raise("CloseHandle")
        except BaseException as error:
            errors.append(("CloseHandle", error))
            return False
    return True


def _cleanup_note(operation: str, error: BaseException) -> str:
    if isinstance(error, OSError):
        winerror = getattr(error, "winerror", None)
        code = winerror if winerror is not None else error.errno
        return (
            f"Windows launch cleanup failed during {operation}: "
            f"{type(error).__name__} ({code})"
        )
    return f"Windows launch cleanup failed during {operation}: {type(error).__name__}"


def _cleanup_after_creation(
    process: _ProcessInformation,
    job: WindowsJob,
    errors: list[tuple[str, BaseException]],
) -> None:
    deadline = time.monotonic() + 5
    try:
        job.terminate()
    except BaseException as error:
        errors.append(("TerminateJobObject", error))
    try:
        job.close()
    except BaseException as error:
        errors.append(("CloseHandle(job)", error))
    if process.hProcess:
        try:
            milliseconds = max(0, int((deadline - time.monotonic()) * 1000))
            result = _kernel32().WaitForSingleObject(process.hProcess, milliseconds)
            if result == _WAIT_TIMEOUT:
                raise TimeoutError("bounded process reap timed out")
            if result == _WAIT_FAILED:
                _raise("WaitForSingleObject")
        except BaseException as error:
            errors.append(("WaitForSingleObject", error))


def launch(
    command: list[str], environment: dict[str, str], stdin_fd: int, stdout_fd: int
) -> _Process:
    """Start an activated wrapper in a kill-on-close job from creation."""
    if not _is_windows or _KERNEL32 is None:
        raise CondaError("Windows launcher is unavailable on this platform.")
    handles: list[int] = []
    attributes: _AttributeList | None = None
    process = _ProcessInformation()
    job: WindowsJob | None = None
    created = False
    try:
        job = WindowsJob()
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
        attributes = _attribute_list(handles, job.handle)
        startup = _StartupInfo()
        startup.cb = ctypes.sizeof(startup)
        startup.dwFlags = _STARTF_USESTDHANDLES
        startup.hStdInput, startup.hStdOutput, startup.hStdError = (
            null,
            diagnostic,
            diagnostic,
        )
        startup.lpAttributeList = attributes.attributes
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
            _CREATE_UNICODE_ENVIRONMENT | _EXTENDED_STARTUPINFO_PRESENT,
            environment_block,
            None,
            ctypes.byref(startup),
            ctypes.byref(process),
        ):
            _raise("CreateProcessW")
        created = True
        if not _kernel32().CloseHandle(process.hThread):
            _raise("CloseHandle")
        process.hThread = 0
        # Close temporary duplicates before handing process and job ownership to caller.
        if attributes:
            attributes.close()
            attributes = None
        cleanup_errors: list[tuple[str, BaseException]] = []
        for handle in handles[:]:
            if _close_handle(handle, cleanup_errors):
                handles.remove(handle)
        if cleanup_errors:
            raise cleanup_errors[0][1]
        result = _Process(process.hProcess, process.dwProcessId, job)
        process.hProcess, job = 0, None
        return result
    except BaseException as error:
        cleanup_errors: list[tuple[str, BaseException]] = []
        if attributes is not None:
            try:
                attributes.close()
            except BaseException as cleanup:
                cleanup_errors.append(("DeleteProcThreadAttributeList", cleanup))
            attributes = None
        if created and job is not None:
            _cleanup_after_creation(process, job, cleanup_errors)
        elif job is not None:
            try:
                job.close()
            except BaseException as cleanup:
                cleanup_errors.append(("CloseHandle(job)", cleanup))
        for name in ("hThread", "hProcess"):
            handle = getattr(process, name)
            if _close_handle(handle, cleanup_errors):
                setattr(process, name, 0)
        for handle in handles[:]:
            if _close_handle(handle, cleanup_errors):
                handles.remove(handle)
        if not isinstance(error, (KeyError, OSError, RuntimeError, ValueError)):
            for operation, cleanup in cleanup_errors:
                error.add_note(_cleanup_note(operation, cleanup))
            raise
        wrapped = CondaError("Could not create contained Windows launch process.")
        for operation, cleanup in cleanup_errors:
            wrapped.add_note(_cleanup_note(operation, cleanup))
        raise wrapped from error
