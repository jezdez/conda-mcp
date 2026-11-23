from __future__ import annotations

import asyncio
import codecs
import json
import math
import os
import shutil
import signal
import subprocess
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import anyio

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
        executable = os.environ.get("CONDA_EXE") or shutil.which("conda")
        if not executable:
            raise FileNotFoundError(
                "could not find conda. Set CONDA_EXE or add conda to PATH"
            )
        return cls(Path(executable), **kwargs)

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
            creation_flags = 0
            if os.name == "nt":
                from .windows import CREATE_SUSPENDED, WindowsJob

                windows_job = WindowsJob()
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | CREATE_SUSPENDED
            process_options: dict[str, Any] = (
                {"creationflags": creation_flags}
                if os.name == "nt"
                else {"start_new_session": True}
            )
            process = None
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
            except BaseException:
                if process is not None and process.returncode is None:
                    with suppress(OSError):
                        process.kill()
                    await process.wait()
                if windows_job is not None:
                    windows_job.close()
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

            stdout_task = asyncio.create_task(capture(process.stdout))
            stderr_task = asyncio.create_task(capture(process.stderr))
            input_task = asyncio.create_task(send_input())
            wait_task = asyncio.create_task(process.wait())
            tasks = (wait_task, stdout_task, stderr_task, input_task)

            async def stop_process() -> None:
                if os.name == "nt":
                    with suppress(OSError):
                        os.kill(process.pid, signal.CTRL_BREAK_EVENT)
                else:
                    with suppress(OSError):
                        os.killpg(process.pid, signal.SIGTERM)
                try:
                    if not wait_task.done():
                        await asyncio.wait_for(
                            asyncio.shield(wait_task),
                            self.termination_grace_seconds,
                        )
                except TimeoutError:
                    pass

                if os.name == "nt":
                    assert windows_job is not None
                    windows_job.terminate()
                else:
                    with suppress(OSError):
                        os.killpg(process.pid, signal.SIGKILL)
                if not wait_task.done():
                    await wait_task

            timed_out = False
            try:
                _, pending = await asyncio.wait(tasks, timeout=timeout)
                if pending:
                    timed_out = True
                    with anyio.CancelScope(shield=True):
                        await stop_process()
                        for task in (stdout_task, stderr_task, input_task):
                            if not task.done():
                                task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                stdout_result, stderr_result, _ = await asyncio.gather(
                    stdout_task,
                    stderr_task,
                    input_task,
                )
            except asyncio.CancelledError:
                with anyio.CancelScope(shield=True):
                    await stop_process()
                    for task in (stdout_task, stderr_task, input_task):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                raise
            finally:
                if windows_job is not None:
                    windows_job.close()

        stdout, stdout_truncated = stdout_result
        stderr, stderr_truncated = stderr_result
        parsed_json: JsonValue | None = None
        if stdout.strip() and not stdout_truncated:

            def reject_constant(value: str) -> None:
                raise ValueError(value)

            try:
                parsed_json = json.loads(stdout, parse_constant=reject_constant)
            except (json.JSONDecodeError, ValueError):
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
