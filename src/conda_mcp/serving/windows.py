from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any

from conda.common.compat import on_win

from .._windows_job import WindowsJob as _SharedWindowsJob

_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_THREAD_SUSPEND_RESUME = 0x0002
_TH32CS_SNAPTHREAD = 0x00000004
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_RESUME_FAILED = 0xFFFFFFFF

CREATE_SUSPENDED = 0x00000004

if on_win:
    _kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
    _open_process = _kernel32.OpenProcess
    _open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _open_process.restype = wintypes.HANDLE
    _create_snapshot = _kernel32.CreateToolhelp32Snapshot
    _create_snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    _create_snapshot.restype = wintypes.HANDLE
    _thread_first = _kernel32.Thread32First
    _thread_first.argtypes = (wintypes.HANDLE, wintypes.LPVOID)
    _thread_first.restype = wintypes.BOOL
    _thread_next = _kernel32.Thread32Next
    _thread_next.argtypes = (wintypes.HANDLE, wintypes.LPVOID)
    _thread_next.restype = wintypes.BOOL
    _open_thread = _kernel32.OpenThread
    _open_thread.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _open_thread.restype = wintypes.HANDLE
    _resume_thread = _kernel32.ResumeThread
    _resume_thread.argtypes = (wintypes.HANDLE,)
    _resume_thread.restype = wintypes.DWORD
    _close_handle = _kernel32.CloseHandle
    _close_handle.argtypes = (wintypes.HANDLE,)
    _close_handle.restype = wintypes.BOOL
else:

    def _unavailable(*args: Any) -> Any:
        raise RuntimeError("Windows process operations are only available on Windows.")

    _open_process = _unavailable
    _create_snapshot = _unavailable
    _thread_first = _unavailable
    _thread_next = _unavailable
    _open_thread = _unavailable
    _resume_thread = _unavailable
    _close_handle = _unavailable


class _ThreadEntry(ctypes.Structure):
    _fields_ = (
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    )


def _error(operation: str) -> OSError:
    code = getattr(ctypes, "get_last_error", lambda: 0)()
    return OSError(code, f"{operation} failed")


def _open_process_thread(pid: int) -> int:
    snapshot = _create_snapshot(_TH32CS_SNAPTHREAD, 0)
    if snapshot == _INVALID_HANDLE_VALUE:
        raise _error("CreateToolhelp32Snapshot")
    try:
        entry = _ThreadEntry()
        entry.dwSize = ctypes.sizeof(entry)
        available = _thread_first(snapshot, ctypes.byref(entry))
        while available:
            if entry.th32OwnerProcessID == pid:
                thread = _open_thread(_THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                if thread is None:
                    raise _error("OpenThread")
                return thread
            available = _thread_next(snapshot, ctypes.byref(entry))
    finally:
        _close_handle(snapshot)
    raise OSError(f"no thread found for suspended process {pid}")


class WindowsJob:
    """Assign a suspended process to a shared job before resuming its thread."""

    def __init__(self) -> None:
        self._job = _SharedWindowsJob()

    def assign_and_resume(self, pid: int) -> None:
        process = _open_process(_PROCESS_TERMINATE | _PROCESS_SET_QUOTA, False, pid)
        if process is None:
            raise _error("OpenProcess")
        try:
            self._job.assign_process(process)
        finally:
            _close_handle(process)
        thread = _open_process_thread(pid)
        try:
            if _resume_thread(thread) == _RESUME_FAILED:
                raise _error("ResumeThread")
        finally:
            _close_handle(thread)

    def terminate(self) -> None:
        self._job.terminate()

    def close(self) -> None:
        self._job.close()
