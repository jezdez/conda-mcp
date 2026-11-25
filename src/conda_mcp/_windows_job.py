from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Any

from conda.common.compat import on_win

if on_win:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _create_job = _kernel32.CreateJobObjectW
    _create_job.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _create_job.restype = wintypes.HANDLE
    _close_handle = _kernel32.CloseHandle
    _close_handle.argtypes = [wintypes.HANDLE]
    _close_handle.restype = wintypes.BOOL
    try:
        import pywintypes

        # pywin32 ships win32job as a native extension without inline typing.
        import win32job  # ty: ignore[import-not-found]
    except ImportError as error:
        if error.name not in {"pywintypes", "win32job"}:
            raise
        pywintypes = None
        win32job = None
        _pywin32_error: ImportError | None = error
    else:
        _pywin32_error = None
else:
    pywintypes = None
    win32job = None
    _pywin32_error = None


def _error(operation: str, error: BaseException) -> OSError:
    code = error.args[0]
    detail = error.args[2]
    return OSError(code, f"{operation} failed: {detail}")


def _cleanup_note(error: BaseException) -> str:
    code = getattr(error, "winerror", None) if isinstance(error, OSError) else None
    if not isinstance(code, int) and isinstance(error, OSError):
        code = error.errno
    if isinstance(code, int):
        return f"CloseHandle cleanup failed: {type(error).__name__}: code={code}"
    return f"CloseHandle cleanup failed: {type(error).__name__}"


class WindowsJob:
    """Own an unnamed Windows job configured to kill its processes on close."""

    def __init__(self) -> None:
        if not on_win:
            raise RuntimeError("Windows job containment is only available on Windows.")
        if sys.getwindowsversion().major < 10:
            raise RuntimeError(
                "Windows job containment requires Windows 10 or Server 2016."
            )
        if pywintypes is None or win32job is None:
            raise RuntimeError(
                "Windows job containment requires pywin32>=311. "
                "Install conda-mcp on Windows with its declared dependencies."
            ) from _pywin32_error
        # pywin32's CreateJobObject wrapper rejects a NULL name. Keep jobs unnamed.
        raw_handle = _create_job(None, None)
        if not raw_handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        try:
            self._handle: Any | None = pywintypes.HANDLE(raw_handle)
        except BaseException as error:
            try:
                if not _close_handle(raw_handle):
                    raise OSError(ctypes.get_last_error(), "CloseHandle failed")
            except BaseException as cleanup:
                error.add_note(_cleanup_note(cleanup))
            raise
        operation = "QueryInformationJobObject"
        try:
            information = win32job.QueryInformationJobObject(
                self._handle, win32job.JobObjectExtendedLimitInformation
            )
            operation = "SetInformationJobObject"
            information["BasicLimitInformation"]["LimitFlags"] |= (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            win32job.SetInformationJobObject(
                self._handle, win32job.JobObjectExtendedLimitInformation, information
            )
        except BaseException as error:
            primary = (
                _error(operation, error)
                if isinstance(error, pywintypes.error)
                else error
            )
            try:
                self.close()
            except BaseException as cleanup:
                primary.add_note(_cleanup_note(cleanup))
            if primary is error:
                raise
            raise primary from error

    @property
    def handle(self) -> int:
        """Return the borrowed native job handle."""
        if self._handle is None:
            raise RuntimeError("Windows job is closed.")
        return int(self._handle)

    def assign_process(self, process_handle: int) -> None:
        """Assign a process using the caller's borrowed process handle."""
        assert pywintypes is not None
        assert win32job is not None
        try:
            win32job.AssignProcessToJobObject(self._handle, process_handle)
        except pywintypes.error as error:
            raise _error("AssignProcessToJobObject", error) from error

    def terminate(self) -> None:
        """Terminate processes assigned to this job without releasing the job."""
        if self._handle is None:
            return
        assert pywintypes is not None
        assert win32job is not None
        try:
            win32job.TerminateJobObject(self._handle, 1)
        except pywintypes.error as error:
            raise _error("TerminateJobObject", error) from error

    def close(self) -> None:
        """Release the owned job handle after a successful native close."""
        if self._handle is None:
            return
        assert pywintypes is not None
        try:
            self._handle.Close()
        except pywintypes.error as error:
            raise _error("CloseHandle", error) from error
        self._handle = None
