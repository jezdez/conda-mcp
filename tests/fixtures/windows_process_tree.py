"""Windows subprocess roles used by native containment integration tests."""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path


def event(access: int, name: str):
    import win32event

    return win32event.OpenEvent(access, False, name)


def signal(name: str) -> None:
    import win32api
    import win32event

    handle = event(0x0002, name)
    try:
        win32event.SetEvent(handle)
    finally:
        win32api.CloseHandle(handle)


def wait(name: str) -> None:
    import win32api
    import win32event

    handle = event(0x00100000, name)
    try:
        win32event.WaitForSingleObject(handle, 30_000)
    finally:
        win32api.CloseHandle(handle)


def record(role: str, **values: object) -> None:
    """Each process writes a separate record, never a shared JSON document."""
    destination = Path(os.environ["WINDOWS_TREE_RECORDS"]).joinpath(f"{role}.json")
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(values), encoding="utf-8")
    temporary.replace(destination)


def grandchild() -> int:
    record("grandchild", pid=os.getpid())
    signal(os.environ["WINDOWS_TREE_READY"])
    if os.environ.get("WINDOWS_TREE_HOLD_STDOUT"):
        sys.stdout.write("GRANDCHILD\n")
        sys.stdout.flush()
    wait(os.environ["WINDOWS_TREE_STOP"])
    return 0


def child() -> int:
    record("child", pid=os.getpid())
    descendant = subprocess.Popen(
        [sys.executable, __file__, "grandchild"], env=os.environ
    )
    wait(os.environ["WINDOWS_TREE_STOP"])
    return descendant.wait()


def root() -> int:
    payload = os.environ.get("_CONDA_MCP_LAUNCH")
    if payload:
        from conda_mcp._launch_windows import restore_protocol

        restore_protocol(json.loads(payload))
    side_effect = os.environ.get("WINDOWS_TREE_SIDE_EFFECT")
    if side_effect:
        Path(side_effect).write_text("root executed", encoding="utf-8")
    record("root", pid=os.getpid())
    descendant = subprocess.Popen([sys.executable, __file__, "child"], env=os.environ)
    wait(os.environ["WINDOWS_TREE_READY"])
    sentinel = os.environ.get("WINDOWS_TREE_SENTINEL_NAME")
    if sentinel:
        import win32event

        inherited = int(os.environ["WINDOWS_TREE_SENTINEL_VALUE"])
        named = win32event.OpenEvent(0x00100000, False, sentinel)
        probe = None
        for library in ("kernelbase", "kernel32"):
            try:
                compare = getattr(
                    ctypes.WinDLL(library, use_last_error=True), "CompareObjectHandles"
                )
            except (AttributeError, OSError):
                continue
            compare.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            compare.restype = wintypes.BOOL
            probe = library, bool(compare(inherited, int(named)))
            break
        import win32api

        win32api.CloseHandle(named)
        if probe is None:
            record(
                "sentinel", completed=False, reason="CompareObjectHandles unavailable"
            )
        else:
            record("sentinel", completed=True, library=probe[0], matched=probe[1])
        if probe is not None and probe[1]:
            Path(os.environ["WINDOWS_TREE_MARKER"]).write_text("inherited")
    signal(os.environ["WINDOWS_TREE_RESULT_READY"])
    if os.environ.get("WINDOWS_TREE_NONZERO"):
        wait(os.environ["WINDOWS_TREE_TESTER_ACK"])
        return int(os.environ["WINDOWS_TREE_NONZERO"])
    if os.environ.get("WINDOWS_TREE_EXIT_ROOT"):
        wait(os.environ["WINDOWS_TREE_TESTER_ACK"])
        return 0
    return descendant.wait()


def duplicate_into_tester(handle: int) -> int:
    import win32api
    import win32con

    target = win32api.OpenProcess(
        win32con.PROCESS_DUP_HANDLE,
        False,
        int(os.environ["WINDOWS_TREE_TESTER_PID"]),
    )
    try:
        duplicated = win32api.DuplicateHandle(
            win32api.GetCurrentProcess(),
            handle,
            target,
            0,
            False,
            win32con.DUPLICATE_SAME_ACCESS,
        )
        # This value belongs to the tester. Detach prevents PyHANDLE from
        # closing that same numeric value in this owner process on teardown.
        return int(duplicated.Detach())
    finally:
        win32api.CloseHandle(target)


def launcher_owner() -> int:
    from conda_mcp._launch_windows import launch

    reader, writer = os.pipe()
    output_reader, output_writer = os.pipe()
    os.close(writer)
    process = launch(
        [sys.executable, __file__, "root"],
        os.environ | {"_CONDA_MCP_LAUNCH": "{}"},
        reader,
        output_writer,
    )
    record(
        "owner",
        pid=os.getpid(),
        child=process.pid,
        handle=duplicate_into_tester(process._handle),
    )
    if os.environ.get("WINDOWS_TREE_OWNER_WAIT"):
        wait(os.environ["WINDOWS_TREE_READY"])
    signal(os.environ["WINDOWS_TREE_OWNER_READY"])
    if os.environ.get("WINDOWS_TREE_OWNER_WAIT"):
        wait(os.environ["WINDOWS_TREE_OWNER_DIE"])
    os._exit(0)


def executor_owner() -> int:
    from conda_mcp.serving.execution import CondaExecutor

    async def run() -> None:
        executor = CondaExecutor(Path(sys.executable), timeout_seconds=20)
        asyncio.create_task(executor.execute((__file__, "root")))
        await asyncio.to_thread(wait, os.environ["WINDOWS_TREE_READY"])
        record("owner", pid=os.getpid())
        signal(os.environ["WINDOWS_TREE_OWNER_READY"])
        wait(os.environ["WINDOWS_TREE_TESTER_ACK"])
        wait(os.environ["WINDOWS_TREE_OWNER_DIE"])
        os._exit(0)

    asyncio.run(run())
    return 0


def enclosing() -> int:
    import win32api
    import win32job

    job = win32job.CreateJobObject(None, None)
    limits = win32job.QueryInformationJobObject(
        job, win32job.JobObjectExtendedLimitInformation
    )
    limits["BasicLimitInformation"]["LimitFlags"] = 0
    if os.environ.get("WINDOWS_TREE_ACTIVE_LIMIT"):
        limits["BasicLimitInformation"]["LimitFlags"] = (
            win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        )
        limits["BasicLimitInformation"]["ActiveProcessLimit"] = 1
    win32job.SetInformationJobObject(
        job, win32job.JobObjectExtendedLimitInformation, limits
    )
    win32job.AssignProcessToJobObject(job, win32api.GetCurrentProcess())
    record(
        "enclosing-prelaunch",
        entered=True,
        limit_flags=int(limits["BasicLimitInformation"]["LimitFlags"]),
        active_process_limit=int(limits["BasicLimitInformation"]["ActiveProcessLimit"]),
        active_limit=bool(os.environ.get("WINDOWS_TREE_ACTIVE_LIMIT")),
    )
    try:
        return launcher_owner()
    except BaseException as error:
        cause = error.__cause__
        record(
            "enclosing-result",
            error=type(error).__name__,
            cause=type(cause).__name__ if cause else None,
            cause_winerror=getattr(cause, "winerror", None)
            or getattr(cause, "errno", None),
            message=str(error),
        )
        raise


def main() -> int:
    roles = {
        "grandchild": grandchild,
        "child": child,
        "root": root,
        "launcher-owner": launcher_owner,
        "executor-owner": executor_owner,
        "enclosing": enclosing,
    }
    return roles[sys.argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main())
