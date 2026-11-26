from __future__ import annotations

import asyncio
import codecs
import json
import math
import os
import re
import signal
import subprocess
import sys
import sysconfig
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
from conda.common.compat import on_win

from .models import Diagnostic, ExecutionResult, Plugin, Program

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any

    from .models import JsonValue


class CompletionQueryError(RuntimeError):
    """Report a bounded conda-completion query failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_WINDOWS_CLEANUP_SECONDS = 5
_MAX_PARSED_JSON_DEPTH = 64


def _add_cleanup_note(error: BaseException, operation: str, detail: object) -> None:
    note = f"Windows executor cleanup {operation}: {type(detail).__name__}"
    code = getattr(detail, "winerror", None)
    if not isinstance(code, int):
        code = getattr(detail, "errno", None)
    if isinstance(code, int):
        note += f" code={code}"
    error.add_note(note)


@dataclass(slots=True)
class CondaExecutor:
    """Run commands against one explicitly resolved conda executable."""

    executable: Path
    timeout_seconds: float = 900
    output_limit_bytes: int = 1_048_576
    stdin_limit_bytes: int = 1_048_576
    termination_grace_seconds: float = 2
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.executable = self.executable.expanduser().resolve()
        if self.timeout_seconds <= 0 or not math.isfinite(self.timeout_seconds):
            raise ValueError("timeout_seconds must be finite and greater than zero")
        if self.output_limit_bytes <= 0:
            raise ValueError("output_limit_bytes must be greater than zero")
        if self.stdin_limit_bytes <= 0:
            raise ValueError("stdin_limit_bytes must be greater than zero")
        if self.termination_grace_seconds <= 0 or not math.isfinite(
            self.termination_grace_seconds
        ):
            raise ValueError(
                "termination_grace_seconds must be finite and greater than zero"
            )
        if not self.executable.is_file():
            raise FileNotFoundError(self.executable)
        if self.executable.suffix.casefold() in {".bat", ".cmd"}:
            raise ValueError(
                "conda batch launchers are not supported. "
                "Select conda.exe with --conda-exe"
            )

    @classmethod
    def from_environment(cls, **kwargs: Any) -> CondaExecutor:
        """Resolve the conda that launched this process."""
        executable = Path(sysconfig.get_path("scripts")) / (
            "conda.exe" if on_win else "conda"
        )
        return cls(executable, **kwargs)

    async def execute(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        stdin: str | None = None,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        """Execute *argv* without a shell and capture a bounded result."""
        timeout = self.bounded_timeout(timeout_seconds)
        if cwd is not None and not cwd.is_dir():
            raise NotADirectoryError(cwd)
        stdin_bytes = stdin.encode() if stdin is not None else None
        if stdin_bytes is not None and len(stdin_bytes) > self.stdin_limit_bytes:
            raise ValueError(
                f"stdin exceeds the {self.stdin_limit_bytes}-byte input limit"
            )

        return await self._execute_process(
            (str(self.executable), *argv),
            cwd=cwd,
            stdin=stdin_bytes,
            timeout=timeout,
        )

    def bounded_timeout(self, timeout_seconds: float | None = None) -> float:
        """Return a valid timeout no greater than the server limit."""
        timeout = (
            timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        )
        if timeout <= 0 or not math.isfinite(timeout):
            raise ValueError("timeout_seconds must be finite and greater than zero")
        return min(timeout, self.timeout_seconds)

    async def discover(self) -> Program:
        """Discover the CLI catalog for this conda installation."""
        from .discovery import discover_program

        try:
            return discover_program()
        # ponytail: generate_parser runs every installed plugin's configure_parser.
        except Exception as error:
            return Program(
                prog=self.executable.name or "conda",
                conda_version="unknown",
                root=None,
                diagnostics=(Diagnostic(path=(), reason=str(error)[:512]),),
            )

    async def discover_plugin_state(self) -> tuple[str, tuple[Plugin, ...]]:
        """Return this conda's version and external plugin entry points."""
        from .discovery import discover_plugins

        return discover_plugins()

    async def probe_plugin_fingerprint(self) -> str:
        """Inspect installed plugin hooks outside the MCP server process."""
        result = await self._execute_process(
            (sys.executable, "-I", "-m", "conda_mcp.serving._plugin_probe"),
            cwd=None,
            stdin=None,
            timeout=min(self.timeout_seconds, 30),
        )
        digest = result.stdout.strip()
        if (
            result.exit_code != 0
            or result.stdout_truncated
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise RuntimeError("plugin probe failed")
        return digest

    async def inspect_completion_command(
        self,
        command_path: Sequence[str] = (),
    ) -> dict[str, JsonValue]:
        """Query installed conda-completion metadata for one command."""
        from .discovery import inspect_completion_command

        try:
            return inspect_completion_command(command_path)
        except LookupError:
            raise CompletionQueryError("unknown_command") from None
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise CompletionQueryError("invalid_response") from error

    async def _execute_process(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        stdin: bytes | None,
        timeout: float,
    ) -> ExecutionResult:
        async with self._lock:
            started = time.monotonic()
            windows_job: Any = None
            windows_job_closed = False
            creation_flags = 0
            if on_win:
                from .windows import CREATE_SUSPENDED, WindowsJob

                windows_job = WindowsJob()
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | CREATE_SUSPENDED
            process_options: dict[str, Any] = (
                {"creationflags": creation_flags}
                if on_win
                else {"start_new_session": True}
            )
            process = None

            async def collect_windows_tasks(
                tasks: tuple[asyncio.Task[Any], ...], deadline: float
            ) -> BaseException | None:
                done, pending = await asyncio.wait(
                    tasks, timeout=max(0, deadline - time.monotonic())
                )
                for task in pending:
                    task.cancel()
                if pending:
                    done_after_cancel, pending = await asyncio.wait(
                        pending, timeout=max(0, deadline - time.monotonic())
                    )
                    done |= done_after_cancel
                task_error = None
                for task in done:
                    if task.cancelled():
                        continue
                    try:
                        task.result()
                    except asyncio.CancelledError:
                        continue
                    except BaseException as error:
                        if task_error is None:
                            task_error = error
                        elif task_error is not error:
                            _add_cleanup_note(task_error, "collect", error)
                if pending:
                    for task in pending:
                        task.add_done_callback(
                            lambda done_task: (
                                None if done_task.cancelled() else done_task.exception()
                            )
                        )
                    timeout_error = RuntimeError("Windows executor cleanup timed out")
                    if task_error is not None:
                        _add_cleanup_note(task_error, "collect", timeout_error)
                        return task_error
                    return timeout_error
                return task_error

            async def await_windows_cleanup(
                cleanup_task: asyncio.Task[None],
            ) -> None:
                cancellation_error: asyncio.CancelledError | None = None
                while True:
                    try:
                        await asyncio.shield(cleanup_task)
                    except asyncio.CancelledError as error:
                        if cancellation_error is None:
                            cancellation_error = error
                        if cleanup_task.done():
                            raise cancellation_error
                        continue
                    except BaseException as error:
                        if cancellation_error is not None:
                            _add_cleanup_note(cancellation_error, "collect", error)
                            raise cancellation_error
                        raise
                    if cancellation_error is not None:
                        raise cancellation_error
                    return

            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdin=(
                        asyncio.subprocess.PIPE
                        if stdin is not None
                        else asyncio.subprocess.DEVNULL
                    ),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    **process_options,
                )
                if windows_job is not None:
                    windows_job.assign_and_resume(process.pid)
            except BaseException as error:
                if windows_job is not None:
                    try:
                        if process is not None:
                            deadline = time.monotonic() + _WINDOWS_CLEANUP_SECONDS

                            async def cleanup_launch_failure(
                                primary_error: BaseException = error,
                            ) -> None:
                                nonlocal windows_job_closed
                                try:
                                    try:
                                        windows_job.terminate()
                                    except BaseException as cleanup_error:
                                        _add_cleanup_note(
                                            primary_error, "terminate", cleanup_error
                                        )
                                    try:
                                        process.kill()
                                    except BaseException as cleanup_error:
                                        _add_cleanup_note(
                                            primary_error, "kill", cleanup_error
                                        )
                                    try:
                                        windows_job.close()
                                        windows_job_closed = True
                                    except BaseException as cleanup_error:
                                        _add_cleanup_note(
                                            primary_error, "close", cleanup_error
                                        )
                                    reaper = asyncio.create_task(process.wait())
                                    cleanup_error = await collect_windows_tasks(
                                        (reaper,), deadline
                                    )
                                    if cleanup_error is not None:
                                        _add_cleanup_note(
                                            primary_error, "reap", cleanup_error
                                        )
                                finally:
                                    if not windows_job_closed:
                                        try:
                                            windows_job.close()
                                            windows_job_closed = True
                                        except BaseException as cleanup_error:
                                            _add_cleanup_note(
                                                primary_error, "close", cleanup_error
                                            )

                            try:
                                cleanup_task = asyncio.create_task(
                                    cleanup_launch_failure()
                                )
                                with anyio.CancelScope(shield=True):
                                    await await_windows_cleanup(cleanup_task)
                            except BaseException as cleanup_error:
                                _add_cleanup_note(error, "reap", cleanup_error)
                    finally:
                        if not windows_job_closed:
                            try:
                                windows_job.close()
                                windows_job_closed = True
                            except BaseException as cleanup_error:
                                _add_cleanup_note(error, "close", cleanup_error)
                raise
            assert process.stdout is not None
            assert process.stderr is not None

            async def capture(
                stream: asyncio.StreamReader,
            ) -> tuple[str, bool]:
                content = bytearray()
                truncated = False
                try:
                    while chunk := await stream.read(65_536):
                        available = self.output_limit_bytes - len(content)
                        if available > 0:
                            content.extend(chunk[:available])
                        if len(chunk) > available:
                            truncated = True
                except asyncio.CancelledError:
                    truncated = True
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                return decoder.decode(content, final=not truncated), truncated

            async def send_input() -> None:
                if process.stdin is None or stdin is None:
                    return
                try:
                    process.stdin.write(stdin)
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    process.stdin.close()
                    with suppress(BrokenPipeError, ConnectionResetError):
                        await process.stdin.wait_closed()

            async def wait_for_exit() -> int:
                if not on_win:
                    # Python 3.11's wait() also waits for inherited pipes to close.
                    # Observe the root exit first so we can stop its descendants.
                    while process.returncode is None:
                        await asyncio.sleep(0.01)
                return await process.wait()

            stdout_task = asyncio.create_task(capture(process.stdout))
            stderr_task = asyncio.create_task(capture(process.stderr))
            input_task = asyncio.create_task(send_input())
            wait_task = asyncio.create_task(wait_for_exit())
            tasks = (wait_task, stdout_task, stderr_task, input_task)

            async def stop_process() -> tuple[float | None, BaseException | None]:
                nonlocal windows_job_closed
                if on_win:
                    with suppress(OSError):
                        os.kill(process.pid, signal.CTRL_BREAK_EVENT)
                else:
                    with suppress(OSError):
                        os.killpg(process.pid, signal.SIGTERM)
                graceful_error = None
                try:
                    if not wait_task.done():
                        await asyncio.wait_for(
                            asyncio.shield(wait_task),
                            self.termination_grace_seconds,
                        )
                except TimeoutError:
                    pass
                except BaseException as error:
                    graceful_error = error

                if on_win:
                    deadline = time.monotonic() + _WINDOWS_CLEANUP_SECONDS
                    assert windows_job is not None
                    termination_error = graceful_error
                    try:
                        windows_job.terminate()
                    except BaseException as error:
                        if termination_error is None:
                            termination_error = error
                        else:
                            _add_cleanup_note(termination_error, "terminate", error)
                    try:
                        windows_job.close()
                        windows_job_closed = True
                    except BaseException as error:
                        if termination_error is None:
                            termination_error = error
                        else:
                            _add_cleanup_note(termination_error, "close", error)
                else:
                    with suppress(OSError):
                        os.killpg(process.pid, signal.SIGKILL)
                if not on_win:
                    if not wait_task.done():
                        await wait_task
                    if graceful_error is not None:
                        raise graceful_error
                return (
                    deadline if on_win else None,
                    termination_error if on_win else None,
                )

            async def cancel_and_cleanup() -> None:
                primary_error = None
                deadline = None
                try:
                    deadline, primary_error = await stop_process()
                except BaseException as error:
                    primary_error = error
                for task in (stdout_task, stderr_task, input_task):
                    if not task.done():
                        task.cancel()
                try:
                    if on_win:
                        assert deadline is not None
                        cleanup_error = await collect_windows_tasks(tasks, deadline)
                        if cleanup_error is not None:
                            raise cleanup_error
                    else:
                        await asyncio.gather(*tasks, return_exceptions=True)
                except BaseException as error:
                    if primary_error is None:
                        primary_error = error
                    else:
                        _add_cleanup_note(primary_error, "collect", error)
                if primary_error is not None:
                    raise primary_error

            timed_out = False
            runtime_error: BaseException | None = None
            cleanup_task: asyncio.Task[None] | None = None

            async def cleanup_once() -> None:
                nonlocal cleanup_task
                if cleanup_task is None:
                    cleanup_task = asyncio.create_task(cancel_and_cleanup())
                await await_windows_cleanup(cleanup_task)

            try:
                if on_win:
                    _, pending = await asyncio.wait(tasks, timeout=timeout)
                else:
                    deadline = time.monotonic() + timeout
                    _, pending = await asyncio.wait((wait_task,), timeout=timeout)
                    if not pending:
                        with anyio.CancelScope(shield=True):
                            await stop_process()
                        _, pending = await asyncio.wait(
                            tasks, timeout=max(0, deadline - time.monotonic())
                        )
                if pending:
                    timed_out = True
                    if on_win:
                        with anyio.CancelScope(shield=True):
                            await cleanup_once()
                    else:
                        with anyio.CancelScope(shield=True):
                            await cancel_and_cleanup()
                stdout_result, stderr_result, _ = await asyncio.gather(
                    stdout_task,
                    stderr_task,
                    input_task,
                )
            except BaseException as primary_error:
                runtime_error = primary_error
                try:
                    if on_win:
                        with anyio.CancelScope(shield=True):
                            await cleanup_once()
                    else:
                        with anyio.CancelScope(shield=True):
                            await cancel_and_cleanup()
                except BaseException as cleanup_error:
                    # Cancellation remains the primary error, so cleanup failures
                    # are only retained as diagnostics on the active exception.
                    _add_cleanup_note(primary_error, "collect", cleanup_error)
                raise
            finally:
                if windows_job is not None and not windows_job_closed:
                    try:
                        windows_job.close()
                    except BaseException as close_error:
                        if runtime_error is None:
                            raise
                        _add_cleanup_note(runtime_error, "close", close_error)

        stdout, stdout_truncated = stdout_result
        stderr, stderr_truncated = stderr_result
        parsed_json: JsonValue | None = None
        if stdout.strip() and not stdout_truncated:

            def reject_constant(value: str) -> None:
                raise ValueError(value)

            def finite_float(value: str) -> float:
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError(value)
                return number

            try:
                candidate = json.loads(
                    stdout,
                    parse_constant=reject_constant,
                    parse_float=finite_float,
                )
                pending_values = [(candidate, 0)]
                while pending_values:
                    value, depth = pending_values.pop()
                    if isinstance(value, (dict, list)):
                        if depth >= _MAX_PARSED_JSON_DEPTH:
                            break
                        children = value.values() if isinstance(value, dict) else value
                        pending_values.extend((child, depth + 1) for child in children)
                else:
                    parsed_json = candidate
            except (json.JSONDecodeError, ValueError, RecursionError):
                pass

        return ExecutionResult(
            exit_code=None if timed_out else process.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_ms=round((time.monotonic() - started) * 1000),
            parsed_json=parsed_json,
            timed_out=timed_out,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )
