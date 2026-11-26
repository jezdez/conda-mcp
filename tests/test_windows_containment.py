"""Native Windows containment integration tests using real job objects."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import anyio
import pytest
from conda.common.compat import on_win

from conda_mcp._launch_windows import launch
from conda_mcp.serving.execution import CondaExecutor

TREE = Path(__file__).with_name("fixtures") / "windows_process_tree.py"

pytestmark = pytest.mark.skipif(not on_win, reason="native Windows jobs")


@pytest.fixture
def windows_tree(tmp_path: Path):
    import win32api
    import win32con
    import win32event

    resources: list[
        tuple[
            object, object, object, object, object, object, list[object], list[object]
        ]
    ] = []

    def create(name: str):
        prefix = f"conda-mcp-{os.getpid()}-{tmp_path.name}-{name}"
        ready_name = f"{prefix}-ready"
        stop_name = f"{prefix}-stop"
        owner_name = f"{prefix}-owner"
        result_name = f"{prefix}-result"
        die_name = f"{prefix}-die"
        acknowledgment_name = f"{prefix}-acknowledged"
        ready = win32event.CreateEvent(None, True, False, ready_name)
        stop = win32event.CreateEvent(None, True, False, stop_name)
        owner_ready = win32event.CreateEvent(None, True, False, owner_name)
        result_ready = win32event.CreateEvent(None, True, False, result_name)
        die = win32event.CreateEvent(None, True, False, die_name)
        acknowledged = win32event.CreateEvent(None, True, False, acknowledgment_name)
        handles: list[object] = []
        owners: list[object] = []
        resources.append(
            (stop, ready, owner_ready, result_ready, die, acknowledged, handles, owners)
        )
        records = tmp_path / f"{name}-records"
        records.mkdir()

        def environment(**extra: str) -> dict[str, str]:
            return os.environ | {
                "WINDOWS_TREE_READY": ready_name,
                "WINDOWS_TREE_STOP": stop_name,
                "WINDOWS_TREE_OWNER_READY": owner_name,
                "WINDOWS_TREE_RESULT_READY": result_name,
                "WINDOWS_TREE_OWNER_DIE": die_name,
                "WINDOWS_TREE_TESTER_ACK": acknowledgment_name,
                "WINDOWS_TREE_RECORDS": str(records),
                "WINDOWS_TREE_TESTER_PID": str(os.getpid()),
                **extra,
            }

        def await_ready(owner: bool = False) -> dict[str, int]:
            target = owner_ready if owner else ready
            assert (
                win32event.WaitForSingleObject(target, 5_000) == win32con.WAIT_OBJECT_0
            )
            pids = {
                path.stem: json.loads(path.read_text(encoding="utf-8"))
                for path in records.glob("*.json")
            }
            if owner and "handle" in pids.get("owner", {}):
                return {}
            assert {"root", "child", "grandchild"} <= pids.keys()
            for value in pids.values():
                pid = value.get("pid")
                if isinstance(pid, int):
                    handles.append(
                        win32api.OpenProcess(win32con.SYNCHRONIZE, False, pid)
                    )
            return {
                role: value["pid"] for role, value in pids.items() if "pid" in value
            }

        def owner(process: subprocess.Popen[bytes]) -> subprocess.Popen[bytes]:
            owners.append(
                win32api.OpenProcess(
                    win32con.SYNCHRONIZE | win32con.PROCESS_TERMINATE,
                    False,
                    process.pid,
                )
            )
            return process

        def exited() -> None:
            assert handles
            assert all(
                win32event.WaitForSingleObject(handle, 5_000) == win32con.WAIT_OBJECT_0
                for handle in handles
            )

        def alive() -> None:
            assert handles
            assert all(
                win32event.WaitForSingleObject(handle, 0) == win32con.WAIT_TIMEOUT
                for handle in handles
            )

        return (
            environment,
            await_ready,
            alive,
            exited,
            die,
            records,
            result_ready,
            acknowledged,
            owner,
        )

    yield create

    for (
        stop,
        ready,
        owner_ready,
        result_ready,
        die,
        acknowledged,
        handles,
        owners,
    ) in resources:
        win32event.SetEvent(stop)
        win32event.SetEvent(die)
        win32event.SetEvent(acknowledged)
        for owner in owners:
            if win32event.WaitForSingleObject(owner, 5_000) == win32con.WAIT_TIMEOUT:
                win32api.TerminateProcess(owner, 1)
                assert win32event.WaitForSingleObject(owner, 5_000) == 0
            win32api.CloseHandle(owner)
        for handle in handles:
            win32api.CloseHandle(handle)
        win32api.CloseHandle(ready)
        win32api.CloseHandle(owner_ready)
        win32api.CloseHandle(result_ready)
        win32api.CloseHandle(die)
        win32api.CloseHandle(acknowledged)
        win32api.CloseHandle(stop)


@contextmanager
def launched_tree(environment: dict[str, str], role: str = "root"):
    stdin, writer = os.pipe()
    reader, stdout = os.pipe()
    os.close(writer)
    process = launch(
        [sys.executable, str(TREE), role],
        environment | {"_CONDA_MCP_LAUNCH": "{}"},
        stdin,
        stdout,
    )
    try:
        yield process
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        os.close(stdin)
        os.close(reader)
        os.close(stdout)


def test_native_launch_kills_only_its_own_process_tree(windows_tree):
    first, second = windows_tree("launch-first"), windows_tree("launch-second")
    with launched_tree(first[0]()) as left, launched_tree(second[0]()) as right:
        first[1]()
        second[1]()
        left.kill()
        assert left.wait(timeout=5) != 0
        first[3]()
        assert right.poll() is None
        second[2]()


def test_executor_kills_only_its_own_process_tree(windows_tree):
    contained = windows_tree("executor-contained")
    sibling = windows_tree("executor-sibling")
    separate = sibling[8](
        subprocess.Popen([sys.executable, str(TREE), "root"], env=sibling[0]())
    )
    before = dict(os.environ)
    os.environ.update(contained[0]())
    try:
        executor = CondaExecutor(
            Path(sys.executable), timeout_seconds=10, termination_grace_seconds=0.1
        )

        async def execute() -> object:
            task = asyncio.create_task(
                executor.execute((str(TREE), "root"), timeout_seconds=5)
            )
            await asyncio.to_thread(contained[1])
            return await task

        result = asyncio.run(execute())
        assert result.timed_out
        sibling[1]()
        contained[3]()
        assert separate.poll() is None
        sibling[2]()
    finally:
        os.environ.clear()
        os.environ.update(before)
        if separate.poll() is None:
            separate.kill()
        separate.wait(timeout=5)


@pytest.mark.parametrize(
    ("role", "wait_for_tree"),
    [("launcher-owner", False), ("launcher-owner", True), ("executor-owner", True)],
)
def test_owner_death_closes_assigned_native_job(windows_tree, role, wait_for_tree):
    tree = windows_tree(f"{role}-{wait_for_tree}")
    owner = tree[8](
        subprocess.Popen(
            [sys.executable, str(TREE), role],
            env=tree[0](WINDOWS_TREE_OWNER_WAIT="1" if wait_for_tree else ""),
        )
    )
    try:
        tree[1](owner=True)
        if wait_for_tree:
            import win32event

            tree[1]()
            win32event.SetEvent(tree[7])
            win32event.SetEvent(tree[4])
        assert owner.wait(timeout=5) == 0
        if role == "launcher-owner":
            # The helper duplicated this handle into this process before it exited.
            import win32api
            import win32con
            import win32event

            record = json.loads(
                (Path(tree[5]) / "owner.json").read_text(encoding="utf-8")
            )
            copied = record["handle"]
            assert (
                win32event.WaitForSingleObject(copied, 5_000) == win32con.WAIT_OBJECT_0
            )
            win32api.CloseHandle(copied)
        if wait_for_tree:
            tree[3]()
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)


def test_native_launcher_closes_job_after_root_exit_with_stdout_held_open(windows_tree):
    tree = windows_tree("launcher-held-stdout")
    environment = tree[0](WINDOWS_TREE_EXIT_ROOT="1", WINDOWS_TREE_HOLD_STDOUT="1")
    with launched_tree(environment) as process:
        tree[1]()
        import win32event

        win32event.SetEvent(tree[7])
        assert process.wait(timeout=5) == 0
        tree[3]()


def test_native_launch_reaps_nonzero_exit_and_repeated_wait_is_idempotent(windows_tree):
    tree = windows_tree("nonzero")
    with launched_tree(tree[0](WINDOWS_TREE_NONZERO="23")) as process:
        tree[1]()
        import win32event

        win32event.SetEvent(tree[7])
        assert process.wait(timeout=5) == 23
        assert process.wait(timeout=5) == 23
        process._conda_mcp_close_job()
        tree[3]()


def test_executor_times_out_when_grandchild_holds_stdout_after_root_exit(windows_tree):
    tree = windows_tree("executor-held-stdout")
    before = dict(os.environ)
    os.environ.update(tree[0](WINDOWS_TREE_EXIT_ROOT="1", WINDOWS_TREE_HOLD_STDOUT="1"))
    try:
        executor = CondaExecutor(
            Path(sys.executable), timeout_seconds=10, termination_grace_seconds=0.1
        )

        async def execute() -> object:
            task = asyncio.create_task(
                executor.execute((str(TREE), "root"), timeout_seconds=5)
            )
            await asyncio.to_thread(tree[1])
            import win32event

            win32event.SetEvent(tree[7])
            return await task

        result = asyncio.run(execute())
        assert result.timed_out
        tree[3]()
    finally:
        os.environ.clear()
        os.environ.update(before)


def test_native_executor_creation_cancellation_leaves_no_process_tree(windows_tree):
    tree = windows_tree("creation-cancellation")
    before = dict(os.environ)
    os.environ.update(tree[0]())

    async def cancel_creation() -> None:
        import win32api
        import win32con
        import win32event

        executor = CondaExecutor(
            Path(sys.executable), timeout_seconds=20, termination_grace_seconds=0.1
        )
        loop = asyncio.get_running_loop()
        original = loop._make_subprocess_transport
        created = asyncio.Event()
        captured: list[object] = []
        task: asyncio.Task[object] | None = None

        async def intercept(protocol, *args, **kwargs):
            original_connection_made = protocol.connection_made

            def connection_made(transport):
                process = transport.get_extra_info("subprocess")
                duplicate = win32api.DuplicateHandle(
                    win32api.GetCurrentProcess(),
                    process._handle,
                    win32api.GetCurrentProcess(),
                    0,
                    False,
                    win32con.DUPLICATE_SAME_ACCESS,
                )
                captured.append(duplicate.Detach())
                # This callback runs after Windows created the process but before
                # create_subprocess_exec can return its asyncio Process wrapper.
                assert task is not None
                task.cancel()
                original_connection_made(transport)
                created.set()

            protocol.connection_made = connection_made
            return await original(protocol, *args, **kwargs)

        try:
            loop._make_subprocess_transport = intercept
            task = asyncio.create_task(executor.execute((str(TREE), "root")))
            await asyncio.wait_for(created.wait(), timeout=5)
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)
            assert captured
            import win32con
            import win32event

            assert all(
                win32event.WaitForSingleObject(handle, 5_000) == win32con.WAIT_OBJECT_0
                for handle in captured
            )
            # The root was created suspended, so an exited retained root handle
            # proves cancellation did not strand the pre-assignment child.
            assert not (tree[5] / "root.json").exists()
        finally:
            try:
                if task is not None:
                    if not task.done():
                        task.cancel()
                    done, pending = await asyncio.wait((task,), timeout=5)
                    for completed in done:
                        if not completed.cancelled():
                            completed.exception()
                    assert not pending
            finally:
                loop._make_subprocess_transport = original
                for handle in captured:
                    if (
                        win32event.WaitForSingleObject(handle, 0)
                        == win32con.WAIT_TIMEOUT
                    ):
                        win32api.TerminateProcess(handle, 1)
                        win32event.WaitForSingleObject(handle, 5_000)
                    win32api.CloseHandle(handle)

    try:
        asyncio.run(cancel_creation())
    finally:
        os.environ.clear()
        os.environ.update(before)


@pytest.mark.parametrize("cancel", ["asyncio", "anyio"])
def test_native_executor_cancellation_terminates_assigned_tree(windows_tree, cancel):
    tree = windows_tree(f"cancel-{cancel}")
    before = dict(os.environ)
    os.environ.update(tree[0]())

    async def exercise() -> None:
        executor = CondaExecutor(
            Path(sys.executable), timeout_seconds=20, termination_grace_seconds=0.1
        )
        task = asyncio.create_task(executor.execute((str(TREE), "root")))
        await asyncio.to_thread(tree[1])
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        if cancel == "anyio":

            async def anyio_exercise() -> None:
                executor = CondaExecutor(
                    Path(sys.executable),
                    timeout_seconds=20,
                    termination_grace_seconds=0.1,
                )

                async def execute() -> None:
                    await executor.execute((str(TREE), "root"))

                async with anyio.create_task_group() as group:
                    group.start_soon(execute)
                    await asyncio.to_thread(tree[1])
                    group.cancel_scope.cancel()

            anyio.run(anyio_exercise)
        else:
            asyncio.run(exercise())
        tree[3]()
    finally:
        os.environ.clear()
        os.environ.update(before)


def test_native_launch_excludes_unrelated_inheritable_sentinel_handle(
    windows_tree, tmp_path
):
    import win32api
    import win32con
    import win32event

    tree = windows_tree("sentinel")
    marker = tmp_path / "inherited"
    sentinel_name = f"conda-mcp-sentinel-{os.getpid()}"
    sentinel = win32event.CreateEvent(None, True, False, sentinel_name)
    win32api.SetHandleInformation(
        sentinel, win32con.HANDLE_FLAG_INHERIT, win32con.HANDLE_FLAG_INHERIT
    )
    win32event.SetEvent(sentinel)
    try:
        environment = tree[0](
            WINDOWS_TREE_SENTINEL_NAME=sentinel_name,
            WINDOWS_TREE_SENTINEL_VALUE=str(int(sentinel)),
            WINDOWS_TREE_MARKER=str(marker),
        )
        with launched_tree(environment):
            tree[1]()
            import win32event

            assert win32event.WaitForSingleObject(tree[6], 5_000) == 0
            probe = json.loads((tree[5] / "sentinel.json").read_text(encoding="utf-8"))
            assert probe["completed"], probe
            assert probe["matched"] is False
            assert not marker.exists()
    finally:
        win32api.CloseHandle(sentinel)


@pytest.mark.parametrize("active_limit", [False, True])
def test_native_launch_respects_enclosing_job_policy(windows_tree, active_limit):
    import winerror

    tree = windows_tree(f"enclosing-{active_limit}")
    marker = Path(tree[5]) / "child-instructions-ran"
    owner = tree[8](
        subprocess.Popen(
            [sys.executable, str(TREE), "enclosing"],
            env=tree[0](
                WINDOWS_TREE_ACTIVE_LIMIT="1" if active_limit else "",
                WINDOWS_TREE_SIDE_EFFECT=str(marker),
            ),
        )
    )
    try:
        if active_limit:
            assert owner.wait(timeout=5) != 0
            prelaunch = json.loads(
                (tree[5] / "enclosing-prelaunch.json").read_text(encoding="utf-8")
            )
            result = json.loads(
                (tree[5] / "enclosing-result.json").read_text(encoding="utf-8")
            )
            assert prelaunch["active_process_limit"] == 1
            assert result["error"] == "CondaError"
            assert result["cause"] == "OSError"
            assert result["cause_winerror"] == winerror.ERROR_NOT_ENOUGH_QUOTA
            assert not (tree[5] / "root.json").exists()
            assert not marker.exists()
        else:
            tree[1](owner=True)
            assert owner.wait(timeout=5) == 0
            import win32api
            import win32event

            record = json.loads((tree[5] / "owner.json").read_text(encoding="utf-8"))
            handle = record["handle"]
            try:
                assert win32event.WaitForSingleObject(handle, 5_000) == 0
            finally:
                win32api.CloseHandle(handle)
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)
