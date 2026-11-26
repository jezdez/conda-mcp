from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import anyio
import pytest
from conda.common.compat import on_win

from conda_mcp.serving.execution import CompletionQueryError, CondaExecutor


class _WindowsProcess:
    def __init__(
        self,
        events: list[str],
        *,
        reap: bool = True,
        returncode: int | None = None,
        kill_error: BaseException | None = None,
        wait_error: BaseException | None = None,
        wait_error_on_cancel: BaseException | None = None,
        suppress_wait_cancellation: bool = False,
    ) -> None:
        self.events = events
        self.pid = 123
        self.returncode = returncode
        self.kill_error = kill_error
        self.wait_error = wait_error
        self.wait_error_on_cancel = wait_error_on_cancel
        self.suppress_wait_cancellation = suppress_wait_cancellation
        self.stdin = None
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self._reap = asyncio.Event()
        self.wait_cancelled = False
        if reap:
            self._reap.set()

    async def wait(self) -> int:
        self.events.append("wait")
        try:
            await self._reap.wait()
        except asyncio.CancelledError:
            self.wait_cancelled = True
            if self.wait_error_on_cancel is not None:
                raise self.wait_error_on_cancel
            if not self.suppress_wait_cancellation:
                raise
            await self._reap.wait()
        if self.wait_error is not None:
            raise self.wait_error
        self.returncode = 0
        return 0

    def kill(self) -> None:
        self.events.append("kill")
        if self.kill_error is not None:
            raise self.kill_error
        self._reap.set()


class _WindowsJob:
    def __init__(
        self,
        events: list[str],
        *,
        assign_error: BaseException | None = None,
        terminate_error: BaseException | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.assign_error = assign_error
        self.terminate_error = terminate_error
        self.close_error = close_error

    def assign_and_resume(self, pid: int) -> None:
        self.events.append(f"assign:{pid}")
        if self.assign_error is not None:
            raise self.assign_error

    def terminate(self) -> None:
        self.events.append("terminate")
        if self.terminate_error is not None:
            raise self.terminate_error

    def close(self) -> None:
        self.events.append("close")
        if self.close_error is not None:
            raise self.close_error


def _windows_executor(tmp_path: Path) -> CondaExecutor:
    executable = tmp_path / "conda.exe"
    executable.touch()
    return CondaExecutor(
        executable, timeout_seconds=0.01, termination_grace_seconds=0.001
    )


def _install_windows_fakes(
    monkeypatch: pytest.MonkeyPatch,
    process: _WindowsProcess,
    job: _WindowsJob,
) -> None:
    import conda_mcp.serving.execution as execution
    import conda_mcp.serving.windows as windows

    monkeypatch.setattr(
        execution,
        "os",
        SimpleNamespace(name="nt", kill=lambda *_: None),
    )
    monkeypatch.setattr(execution, "on_win", True)
    monkeypatch.setattr(
        execution,
        "signal",
        SimpleNamespace(CTRL_BREAK_EVENT=1, SIGTERM=1, SIGKILL=2),
    )
    monkeypatch.setattr(
        execution,
        "subprocess",
        SimpleNamespace(CREATE_NEW_PROCESS_GROUP=1),
    )
    monkeypatch.setattr(windows, "WindowsJob", lambda: job)

    async def create_process(*_args: object, **_kwargs: object) -> _WindowsProcess:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)


if TYPE_CHECKING:
    pass


@pytest.mark.anyio
async def test_execute_preserves_json_and_argv(
    fake_conda: tuple[CondaExecutor, Path],
) -> None:
    executor, script = fake_conda

    result = await executor.execute(
        [str(script), "json", "--value", "two words", "$(echo unsafe)"],
    )

    assert result.exit_code == 0
    assert result.parsed_json == {
        "argv": ["--value", "two words", "$(echo unsafe)"],
    }


@pytest.mark.anyio
async def test_execute_preserves_streams_and_exit_code(
    fake_conda: tuple[CondaExecutor, Path],
) -> None:
    executor, script = fake_conda

    result = await executor.execute([str(script), "streams"])

    assert result.exit_code == 7
    assert result.stdout == "stdout-value\n"
    assert result.stderr == "stderr-value\n"
    assert result.parsed_json is None


@pytest.mark.anyio
async def test_execute_supports_cwd_and_stdin(
    fake_conda: tuple[CondaExecutor, Path],
    tmp_path: Path,
) -> None:
    executor, script = fake_conda

    cwd_result = await executor.execute([str(script), "cwd"], cwd=tmp_path)
    stdin_result = await executor.execute([str(script), "stdin"], stdin="hello")

    assert cwd_result.stdout.strip() == str(tmp_path)
    assert stdin_result.stdout == "hello\n"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("stdout", "parsed_json"),
    [
        ('{"value": 1}', {"value": 1}),
        (' \n["one", 2]\t', ["one", 2]),
        ('{"value": 1}\n{"value": 2}', None),
        ('prefix {"value": 1}', None),
        ("NaN", None),
        ("Infinity", None),
        ("-Infinity", None),
    ],
)
async def test_execute_parses_exactly_one_json_document(
    fake_conda: tuple[CondaExecutor, Path],
    stdout: str,
    parsed_json: object,
) -> None:
    executor, script = fake_conda

    result = await executor.execute([str(script), "literal", stdout])

    assert result.stdout == stdout
    assert result.parsed_json == parsed_json


@pytest.mark.anyio
async def test_execute_bounds_and_drains_both_output_streams(
    fake_conda: tuple[CondaExecutor, Path],
) -> None:
    executor, script = fake_conda
    executor = CondaExecutor(
        executor.executable,
        output_limit_bytes=1_024,
    )

    result = await executor.execute([str(script), "large-streams", "200000"])

    assert result.exit_code == 0
    assert result.stdout == "o" * 1_024
    assert result.stderr == "e" * 1_024
    assert result.stdout_truncated
    assert result.stderr_truncated
    assert result.parsed_json is None


@pytest.mark.anyio
async def test_execute_truncates_at_a_utf8_character_boundary(
    fake_conda: tuple[CondaExecutor, Path],
) -> None:
    executor, script = fake_conda
    executor = CondaExecutor(executor.executable, output_limit_bytes=3)

    result = await executor.execute([str(script), "literal", "éé"])

    assert result.stdout == "é"
    assert result.stdout_truncated
    assert "�" not in result.stdout


@pytest.mark.anyio
async def test_execute_rejects_oversized_stdin_before_spawning(
    fake_conda: tuple[CondaExecutor, Path],
) -> None:
    executor, script = fake_conda
    executor = CondaExecutor(executor.executable, stdin_limit_bytes=4)

    with pytest.raises(ValueError, match="4-byte input limit"):
        await executor.execute([str(script), "stdin"], stdin="12345")


@pytest.mark.anyio
@pytest.mark.parametrize("timeout", [0, float("inf"), float("nan")])
async def test_execute_rejects_unbounded_timeout_override(
    fake_conda: tuple[CondaExecutor, Path],
    timeout: float,
) -> None:
    executor, script = fake_conda

    with pytest.raises(ValueError, match="finite and greater than zero"):
        await executor.execute(
            [str(script), "literal", "not-started"], timeout_seconds=timeout
        )


@pytest.mark.anyio
async def test_execute_timeout_kills_a_child_that_ignores_termination(
    fake_conda: tuple[CondaExecutor, Path],
    tmp_path: Path,
) -> None:
    executor, script = fake_conda
    started = tmp_path / "timeout-started"
    survived = tmp_path / "timeout-survived"
    executor = CondaExecutor(
        executor.executable,
        timeout_seconds=0.5,
        termination_grace_seconds=0.05,
    )

    result = await executor.execute(
        [str(script), "linger", str(started), str(survived), "1"]
    )
    await asyncio.sleep(1.1)

    assert result.timed_out
    assert result.exit_code is None
    assert started.is_file()
    assert not survived.exists()


@pytest.mark.anyio
async def test_execute_timeout_bounds_inherited_pipe_drain(
    fake_conda: tuple[CondaExecutor, Path],
    tmp_path: Path,
) -> None:
    executor, script = fake_conda
    survived = tmp_path / "timeout-descendant-survived"
    started = time.monotonic()

    result = await executor.execute(
        [str(script), "inherited-pipes", str(survived)], timeout_seconds=0.05
    )
    elapsed = time.monotonic() - started
    await asyncio.sleep(0.55)

    assert result.timed_out
    assert elapsed < 0.3
    assert not survived.exists()


@pytest.mark.anyio
async def test_execute_cancellation_kills_child_and_propagates(
    fake_conda: tuple[CondaExecutor, Path],
    tmp_path: Path,
) -> None:
    executor, script = fake_conda
    started = tmp_path / "cancel-started"
    survived = tmp_path / "cancel-survived"
    executor = CondaExecutor(
        executor.executable,
        termination_grace_seconds=0.05,
    )
    execution = asyncio.create_task(
        executor.execute([str(script), "linger", str(started), str(survived), "1"])
    )
    for _ in range(200):
        if started.exists():
            break
        await asyncio.sleep(0.01)
    assert started.is_file()

    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution
    await asyncio.sleep(1.1)

    assert not survived.exists()


@pytest.mark.anyio
async def test_execute_cancellation_bounds_inherited_pipe_drain(
    fake_conda: tuple[CondaExecutor, Path],
    tmp_path: Path,
) -> None:
    executor, script = fake_conda
    survived = tmp_path / "cancel-descendant-survived"
    execution = asyncio.create_task(
        executor.execute([str(script), "inherited-pipes", str(survived)])
    )
    await asyncio.sleep(0.05)
    assert not execution.done()

    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(execution, 0.2)
    await asyncio.sleep(0.55)

    assert not survived.exists()


@pytest.mark.anyio
async def test_windows_assignment_failure_terminates_job_before_reaping_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    process = _WindowsProcess(events)
    job = _WindowsJob(events, assign_error=OSError("assignment failed"))
    _install_windows_fakes(monkeypatch, process, job)

    with pytest.raises(OSError, match="assignment failed"):
        await _windows_executor(tmp_path).execute(())

    assert events == ["assign:123", "terminate", "kill", "close", "wait"]


@pytest.mark.anyio
async def test_windows_assignment_failure_preserves_primary_error_when_close_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    process = _WindowsProcess(events)
    job = _WindowsJob(
        events,
        assign_error=OSError("assignment failed"),
        close_error=OSError("close failed"),
    )
    _install_windows_fakes(monkeypatch, process, job)

    with pytest.raises(OSError, match="assignment failed"):
        await _windows_executor(tmp_path).execute(())

    assert "close" in events


@pytest.mark.anyio
async def test_windows_cancellation_closes_job_when_teardown_cannot_reap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import conda_mcp.serving.execution as execution

    monkeypatch.setattr(execution, "_WINDOWS_CLEANUP_SECONDS", 0.01)
    events: list[str] = []
    process = _WindowsProcess(events, reap=False)
    process.stdout.feed_eof()
    process.stderr.feed_eof()
    job = _WindowsJob(events)
    _install_windows_fakes(monkeypatch, process, job)
    execution_task = asyncio.create_task(_windows_executor(tmp_path).execute(()))

    await asyncio.sleep(0)
    execution_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution_task

    assert "close" in events


@pytest.mark.anyio
async def test_windows_launch_close_failure_propagates_without_primary_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    process = _WindowsProcess(events)
    process.stdout.feed_eof()
    process.stderr.feed_eof()
    job = _WindowsJob(events, close_error=SystemExit("close failed"))
    _install_windows_fakes(monkeypatch, process, job)

    with pytest.raises(SystemExit, match="close failed"):
        await _windows_executor(tmp_path).execute(())


@pytest.mark.anyio
async def test_windows_assignment_failure_closes_job_after_kill_control_flow_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    process = _WindowsProcess(events, kill_error=SystemExit("kill failed"))
    job = _WindowsJob(events, assign_error=OSError("assignment failed"))
    _install_windows_fakes(monkeypatch, process, job)

    with pytest.raises(OSError, match="assignment failed"):
        await _windows_executor(tmp_path).execute(())

    assert "close" in events


@pytest.mark.anyio
async def test_windows_timeout_terminates_job_after_root_has_exited(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    process = _WindowsProcess(events, returncode=0)
    job = _WindowsJob(events)
    _install_windows_fakes(monkeypatch, process, job)

    result = await _windows_executor(tmp_path).execute(())

    assert result.timed_out
    assert events == ["assign:123", "wait", "terminate", "close"]


@pytest.mark.anyio
async def test_windows_terminate_failure_still_reaps_and_closes_with_one_deadline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import conda_mcp.serving.execution as execution

    monkeypatch.setattr(execution, "_WINDOWS_CLEANUP_SECONDS", 0.01)
    events: list[str] = []
    process = _WindowsProcess(events, reap=False)
    job = _WindowsJob(events, terminate_error=OSError("terminate failed"))
    _install_windows_fakes(monkeypatch, process, job)

    with pytest.raises(OSError, match="terminate failed"):
        await _windows_executor(tmp_path).execute(())

    assert events[:3] == ["assign:123", "wait", "terminate"]
    assert "close" in events
    assert process.wait_cancelled


@pytest.mark.anyio
async def test_windows_cancellation_during_creation_closes_unassigned_job(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    job = _WindowsJob(events)
    _install_windows_fakes(monkeypatch, _WindowsProcess(events), job)
    started = asyncio.Event()

    async def creating(*_args: object, **_kwargs: object) -> _WindowsProcess:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", creating)
    task = asyncio.create_task(_windows_executor(tmp_path).execute(()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert events == ["close"]


@pytest.mark.anyio
async def test_windows_anyio_cancellation_closes_job(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    process = _WindowsProcess(events, reap=False)
    job = _WindowsJob(events)
    _install_windows_fakes(monkeypatch, process, job)

    with anyio.move_on_after(0.01):
        await _windows_executor(tmp_path).execute(())

    assert "close" in events


@pytest.mark.anyio
async def test_windows_repeated_asyncio_cancellation_waits_for_owned_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import conda_mcp.serving.execution as execution

    monkeypatch.setattr(execution, "_WINDOWS_CLEANUP_SECONDS", 0.01)
    events: list[str] = []
    process = _WindowsProcess(events, reap=False)
    job = _WindowsJob(events)
    _install_windows_fakes(monkeypatch, process, job)
    task = asyncio.create_task(_windows_executor(tmp_path).execute(()))

    await asyncio.sleep(0)
    task.cancel()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert process.wait_cancelled
    assert "close" in events


@pytest.mark.anyio
async def test_windows_assignment_cleanup_is_bounded_when_wait_ignores_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import conda_mcp.serving.execution as execution

    monkeypatch.setattr(execution, "_WINDOWS_CLEANUP_SECONDS", 0.01)
    events: list[str] = []
    process = _WindowsProcess(
        events,
        reap=False,
        kill_error=OSError("kill failed"),
        suppress_wait_cancellation=True,
    )
    job = _WindowsJob(events, assign_error=OSError("assignment failed"))
    _install_windows_fakes(monkeypatch, process, job)

    execution_task = asyncio.create_task(_windows_executor(tmp_path).execute(()))
    done, _ = await asyncio.wait({execution_task}, timeout=0.1)
    process._reap.set()
    await asyncio.sleep(0)

    assert execution_task in done
    with pytest.raises(OSError, match="assignment failed"):
        await execution_task
    assert process.wait_cancelled
    assert "close" in events


@pytest.mark.anyio
async def test_windows_timeout_does_not_return_success_when_reap_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    process = _WindowsProcess(events, wait_error=OSError(91, "wait failed"))
    job = _WindowsJob(events)
    _install_windows_fakes(monkeypatch, process, job)

    with pytest.raises(OSError) as raised:
        await _windows_executor(tmp_path).execute(())

    assert raised.value.errno == 91
    assert "terminate" in events
    assert "close" in events


@pytest.mark.anyio
async def test_windows_assignment_failure_notes_reap_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    process = _WindowsProcess(events, wait_error=OSError(92, "wait failed"))
    job = _WindowsJob(events, assign_error=OSError("assignment failed"))
    _install_windows_fakes(monkeypatch, process, job)

    with pytest.raises(OSError, match="assignment failed") as raised:
        await _windows_executor(tmp_path).execute(())

    assert raised.value.__notes__ == ["Windows executor cleanup reap: OSError code=92"]


@pytest.mark.anyio
async def test_windows_graceful_wait_failure_still_forces_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    process = _WindowsProcess(
        events,
        reap=False,
        wait_error_on_cancel=OSError(93, "wait failed"),
    )
    job = _WindowsJob(events)
    _install_windows_fakes(monkeypatch, process, job)

    with pytest.raises(OSError) as raised:
        await _windows_executor(tmp_path).execute(())

    assert raised.value.errno == 93
    assert "terminate" in events
    assert "close" in events
    assert process.wait_cancelled


@pytest.mark.anyio
async def test_windows_grace_failure_preserves_deadline_and_collects_streams(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    process = _WindowsProcess(events, reap=False)
    failure = OSError(94, "private wait detail")
    job = _WindowsJob(events)
    _install_windows_fakes(monkeypatch, process, job)

    async def failed_wait():
        await asyncio.sleep(0.015)
        raise failure

    monkeypatch.setattr(process, "wait", failed_wait)
    executor = CondaExecutor(
        _windows_executor(tmp_path).executable,
        timeout_seconds=0.01,
        termination_grace_seconds=0.1,
    )
    with pytest.raises(OSError) as raised:
        await executor.execute(())

    assert raised.value is failure
    assert "terminate" in events and "close" in events
    assert not any(
        "AssertionError" in note for note in getattr(failure, "__notes__", ())
    )
    assert not any(
        not task.done()
        and task is not asyncio.current_task()
        and "capture" in task.get_coro().__qualname__
        for task in asyncio.all_tasks()
    )


@pytest.mark.anyio
async def test_windows_cleanup_preserves_first_direct_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import conda_mcp.serving.execution as execution

    monkeypatch.setattr(execution, "_WINDOWS_CLEANUP_SECONDS", 0.05)
    events: list[str] = []
    process = _WindowsProcess(events, reap=False)
    job = _WindowsJob(events)
    _install_windows_fakes(monkeypatch, process, job)
    task = asyncio.create_task(_windows_executor(tmp_path).execute(()))

    await asyncio.sleep(0)
    task.cancel("first cancellation")
    await asyncio.sleep(0)
    task.cancel("second cancellation")
    with pytest.raises(asyncio.CancelledError) as raised:
        await task

    assert raised.value.args == ("first cancellation",)
    assert process.wait_cancelled


@pytest.mark.anyio
async def test_execute_timeout_override_cannot_raise_server_limit(
    fake_conda: tuple[CondaExecutor, Path],
    tmp_path: Path,
) -> None:
    executor, script = fake_conda
    executor = CondaExecutor(executor.executable, timeout_seconds=0.05)

    result = await executor.execute(
        [str(script), "serialize", str(tmp_path / "log"), "one", "0.5"],
        timeout_seconds=10,
    )

    assert result.timed_out


@pytest.mark.anyio
async def test_executor_serializes_processes(
    fake_conda: tuple[CondaExecutor, Path],
    tmp_path: Path,
) -> None:
    executor, script = fake_conda
    log = tmp_path / "execution-order"

    await asyncio.gather(
        executor.execute([str(script), "serialize", str(log), "one", "0.1"]),
        executor.execute([str(script), "serialize", str(log), "two", "0.1"]),
    )

    assert log.read_text().splitlines() in (
        ["start-one", "end-one", "start-two", "end-two"],
        ["start-two", "end-two", "start-one", "end-one"],
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {"timeout_seconds": 0},
        {"timeout_seconds": float("inf")},
        {"timeout_seconds": float("nan")},
        {"output_limit_bytes": 0},
        {"stdin_limit_bytes": 0},
        {"termination_grace_seconds": 0},
        {"termination_grace_seconds": float("inf")},
        {"termination_grace_seconds": float("nan")},
    ],
)
def test_executor_rejects_invalid_limits(
    tmp_path: Path,
    arguments: dict[str, float],
) -> None:
    executable = tmp_path / "conda"
    executable.touch()

    with pytest.raises(ValueError, match="greater than zero"):
        CondaExecutor(executable, **arguments)


@pytest.mark.parametrize("suffix", [".bat", ".cmd", ".CMD"])
def test_executor_rejects_batch_launchers(tmp_path: Path, suffix: str) -> None:
    executable = tmp_path / f"conda{suffix}"
    executable.touch()

    with pytest.raises(ValueError, match="conda.exe"):
        CondaExecutor(executable)


@pytest.mark.anyio
@pytest.mark.parametrize("override", ["CONDA_EXE", "PATH"])
async def test_executor_uses_discovered_installation_despite_ambient_conda(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, override: str
) -> None:
    if override == "CONDA_EXE":
        monkeypatch.setenv("CONDA_EXE", sys.executable)
    else:
        monkeypatch.delenv("CONDA_EXE", raising=False)
        monkeypatch.setenv("PATH", str(tmp_path))

    executor = CondaExecutor.from_environment(timeout_seconds=30)
    program = await executor.discover()
    result = await executor.execute(("info", "--json"))

    assert result.exit_code == 0, result.stderr
    assert isinstance(result.parsed_json, dict)
    assert Path(result.parsed_json["conda_prefix"]).samefile(sys.prefix)
    assert result.parsed_json["conda_version"] == program.conda_version


@pytest.mark.anyio
async def test_discover_live_conda_installation() -> None:
    try:
        executor = CondaExecutor.from_environment(timeout_seconds=30)
    except FileNotFoundError:
        pytest.skip("conda is not installed")

    info_result = await executor.execute(("info", "--json"))
    program = await executor.discover()

    assert isinstance(info_result.parsed_json, dict)
    assert program.conda_version == info_result.parsed_json["conda_version"]
    assert program.root is not None
    assert {"env", "info", "install"} <= {child.name for child in program.root.children}


@pytest.mark.anyio
@pytest.mark.parametrize("error", [RuntimeError, ValueError])
async def test_discover_reports_parser_failure_without_raising(
    monkeypatch: pytest.MonkeyPatch,
    error: type[Exception],
) -> None:
    import conda.cli.conda_argparse

    def explode():
        raise error("parser unavailable")

    monkeypatch.setattr(conda.cli.conda_argparse, "generate_parser", explode)
    executor = CondaExecutor(Path(sys.executable))

    program = await executor.discover()

    assert program.root is None
    assert program.diagnostics[0].reason == "parser unavailable"


@pytest.mark.anyio
async def test_discover_rejects_stdout_noise(monkeypatch: pytest.MonkeyPatch) -> None:
    import argparse

    import conda.cli.conda_argparse

    def noisy():
        print("plugin chatter")
        return argparse.ArgumentParser(prog="conda")

    monkeypatch.setattr(conda.cli.conda_argparse, "generate_parser", noisy)
    executor = CondaExecutor(Path(sys.executable))

    program = await executor.discover()

    assert program.root is None
    assert "wrote to stdout" in program.diagnostics[0].reason


@pytest.mark.anyio
async def test_completion_unknown_path_maps_to_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import conda_mcp.serving.discovery as discovery

    def unknown(_path):
        raise LookupError("unknown_command")

    monkeypatch.setattr(discovery, "inspect_completion_command", unknown)
    executor = CondaExecutor(Path(sys.executable))

    with pytest.raises(CompletionQueryError, match="unknown_command"):
        await executor.inspect_completion_command(["nope"])


@pytest.mark.anyio
async def test_shell_activation_returns_code_without_mutating_server_environment() -> (
    None
):
    try:
        executor = CondaExecutor.from_environment(timeout_seconds=30)
    except FileNotFoundError:
        pytest.skip("conda is not installed")
    previous_prefix = os.environ.get("CONDA_PREFIX")

    result = await executor.execute(("shell.posix", "activate"))

    assert result.exit_code == 0
    assert result.stdout
    assert os.environ.get("CONDA_PREFIX") == previous_prefix


def test_executor_rejects_a_missing_executable(tmp_path):
    with pytest.raises(FileNotFoundError):
        CondaExecutor(tmp_path / "missing")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.anyio
@pytest.mark.skipif(on_win, reason="POSIX executable permissions")
async def test_launch_permission_failure_propagates_without_a_child(tmp_path):
    executable = tmp_path / "not-executable"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o600)
    with pytest.raises(PermissionError):
        await CondaExecutor(executable).execute(())


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error",
    [TypeError("malformed"), ValueError("malformed"), AttributeError("malformed")],
)
async def test_completion_invalid_metadata_maps_to_a_query_error(monkeypatch, error):
    def fail(_path):
        raise error

    monkeypatch.setattr("conda_mcp.serving.discovery.inspect_completion_command", fail)
    with pytest.raises(CompletionQueryError, match="invalid_response") as caught:
        await CondaExecutor(Path(sys.executable)).inspect_completion_command(())
    assert caught.value.__cause__ is error


@pytest.mark.anyio
async def test_child_closing_stdin_does_not_hide_its_exit_status():
    executor = CondaExecutor(Path(sys.executable))
    result = await executor.execute(
        ["-c", "import os, time\nos.close(0)\ntime.sleep(0.1)\nraise SystemExit(7)"],
        stdin="x" * 1_048_576,
    )
    assert result.exit_code == 7
    assert not result.timed_out


@pytest.mark.anyio
@pytest.mark.parametrize("terminate_fails", [False, True])
async def test_windows_timeout_preserves_cleanup_failures(
    monkeypatch, tmp_path, terminate_fails
):
    events = []
    process = _WindowsProcess(events, reap=False)
    process.stdout.feed_eof()
    process.stderr.feed_eof()
    close_error = OSError(5, "close failed")
    terminate_error = OSError(6, "terminate failed") if terminate_fails else None
    job = _WindowsJob(events, close_error=close_error, terminate_error=terminate_error)
    _install_windows_fakes(monkeypatch, process, job)
    import conda_mcp.serving.execution as execution

    monkeypatch.setattr(execution, "_WINDOWS_CLEANUP_SECONDS", 0.01)
    with pytest.raises(OSError) as caught:
        await _windows_executor(tmp_path).execute(())
    assert caught.value is (terminate_error or close_error)
    assert "terminate" in events and "close" in events
    assert process.wait_cancelled
    if terminate_fails:
        assert any("close" in note for note in caught.value.__notes__)


@pytest.mark.anyio
async def test_windows_assignment_failure_remains_primary_when_termination_fails(
    monkeypatch, tmp_path
):
    events = []
    error = OSError(5, "assignment failed")
    process = _WindowsProcess(events)
    job = _WindowsJob(
        events, assign_error=error, terminate_error=OSError(6, "terminate failed")
    )
    _install_windows_fakes(monkeypatch, process, job)
    with pytest.raises(OSError) as caught:
        await _windows_executor(tmp_path).execute(())
    assert caught.value is error
    assert any("terminate" in note for note in error.__notes__)
    assert events.index("kill") < events.index("wait")
    assert "close" in events
