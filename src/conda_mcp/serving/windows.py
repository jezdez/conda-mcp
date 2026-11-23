"""Contain Windows conda subprocess trees in kill-on-close job objects."""

from __future__ import annotations

import importlib
from typing import Any

_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100


def _win32() -> tuple[Any, Any]:
    """Import the pywin32 bindings used to own a job object."""
    try:
        return (
            importlib.import_module("win32api"),
            importlib.import_module("win32job"),
        )
    except ImportError as error:
        # A noarch conda package cannot require a Windows-only dependency, so
        # this is the only place the requirement can fail.
        raise OSError("pywin32 is required to contain Windows process trees") from error


class WindowsJob:
    """Own a Windows job object that tracks one subprocess tree."""

    def __init__(self) -> None:
        win32api, win32job = _win32()
        self._api = win32api
        self._job = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(
            self._job, win32job.JobObjectExtendedLimitInformation
        )
        info["BasicLimitInformation"]["LimitFlags"] |= (
            win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        win32job.SetInformationJobObject(
            self._job, win32job.JobObjectExtendedLimitInformation, info
        )

    def assign(self, pid: int) -> None:
        """Assign a just-spawned process so its descendants join the job."""
        _, win32job = _win32()
        try:
            process = self._api.OpenProcess(
                _PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid
            )
        # ponytail: the child can exit before this call. Nothing to contain then.
        except Exception:
            return
        try:
            win32job.AssignProcessToJobObject(self._job, process)
        finally:
            self._api.CloseHandle(process)

    def terminate(self) -> None:
        """Terminate every process still assigned to the job."""
        _, win32job = _win32()
        if self._job:
            win32job.TerminateJobObject(self._job, 1)

    def close(self) -> None:
        """Release the job handle and terminate any remaining processes."""
        if self._job:
            self._api.CloseHandle(self._job)
            self._job = None
