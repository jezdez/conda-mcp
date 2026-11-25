"""Launch a recorded executable with native conda activation."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import TYPE_CHECKING, cast

from conda import CondaError
from conda.base.context import context
from conda.common.compat import on_win
from conda.utils import wrap_subprocess_call

from . import _launch_windows
from .files import load_json
from .servers import discover

if TYPE_CHECKING:
    from .servers import Server


_PAYLOAD = "_CONDA_MCP_LAUNCH"
_PAYLOAD_LIMIT = 65536
_UNSAFE_POSIX = '"$`\\\r\n'


@dataclass(frozen=True)
class LaunchPayload:
    """Validated execution inputs retained across native conda activation."""

    argv: tuple[str, ...]
    required: tuple[str, ...]
    cwd: str
    prefix: str
    name: str
    package: str
    manifest: str
    digest: str
    executable: str
    stdin: int = 0
    stdout: int = 1
    stdin_handle: int | None = None
    stdout_handle: int | None = None
    identity: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        """Reject malformed launch data before it can select files or descriptors."""
        if (
            any(
                not isinstance(value, str) or "\0" in value
                for value in (
                    self.cwd,
                    self.prefix,
                    self.name,
                    self.package,
                    self.manifest,
                    self.digest,
                    self.executable,
                )
            )
            or not all(
                Path(value).is_absolute()
                for value in (
                    self.cwd,
                    self.prefix,
                    self.manifest,
                    self.executable,
                )
            )
            or any(
                ".." in Path(value).parts
                for value in (self.prefix, self.manifest, self.executable)
            )
            or Path(self.manifest)
            != Path(self.prefix) / "share/conda-mcp/servers" / f"{self.name}.json"
            or not Path(self.executable).is_relative_to(self.prefix)
            or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", self.name)
            or not self.package
            or not re.fullmatch(r"[0-9a-f]{64}", self.digest)
            or not self.argv
            or self.argv[0] != self.executable
            or any(not isinstance(value, str) or "\0" in value for value in self.argv)
            or any(
                not isinstance(value, str)
                or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value)
                for value in self.required
            )
            or any(
                type(value) is not int or value < 0
                for value in (self.stdin, self.stdout)
            )
            or self.stdin == self.stdout
            or any(
                value is not None and (type(value) is not int or value <= 0)
                for value in (self.stdin_handle, self.stdout_handle)
            )
            or (self.stdin_handle is None) != (self.stdout_handle is None)
            or len(self.identity) != 5
            or any(type(value) is not int for value in self.identity)
        ):
            raise ValueError("invalid launch payload")

    def dump(self) -> str:
        """Serialize bounded, literal execution data for the trampoline environment."""
        value = json.dumps(asdict(self), ensure_ascii=False, allow_nan=False)
        if len(value.encode()) > _PAYLOAD_LIMIT:
            raise CondaError("MCP launch arguments are too large.")
        return value

    @classmethod
    def decode(cls, value: str) -> LaunchPayload:
        """Decode exact reserved fields without coercing untrusted field values."""
        if len(value.encode("utf-8")) > _PAYLOAD_LIMIT:
            raise ValueError("launch payload is too large")
        raw: dict = load_json(value.encode("utf-8"))
        if set(raw) != {field.name for field in fields(cls)}:
            raise ValueError("invalid launch payload")
        for key in ("argv", "required", "identity"):
            if not isinstance(raw[key], list):
                raise ValueError("invalid launch payload")
            raw[key] = tuple(raw[key])
        return cls(**raw)

    def revalidate(self) -> Path:
        """Verify post-activation inputs and return the freshly checked executable."""
        if os.environ.get("CONDA_PREFIX") != self.prefix:
            raise CondaError("Conda activation selected an unexpected prefix.")
        server = next(
            (item for item in discover(Path(self.prefix)) if item.name == self.name),
            None,
        )
        if server is None or (
            server.package,
            str(server.manifest),
            server.manifest_digest,
        ) != (self.package, self.manifest, self.digest):
            raise CondaError("MCP server changed during activation.")
        executable = server.resolve_executable()
        info = executable.stat()
        if (
            str(executable) != self.executable
            or (
                info.st_dev,
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            )
            != self.identity
        ):
            raise CondaError("MCP executable changed during activation.")
        missing = [name for name in self.required if name not in os.environ]
        if missing:
            raise CondaError(
                "Missing required environment variables: " + ", ".join(missing)
            )
        return executable

    def restore_protocol(self) -> None:
        """Give only the validated server access to the saved protocol streams."""
        if on_win:
            _launch_windows.restore_protocol(
                {
                    "stdin_handle": self.stdin_handle,
                    "stdout_handle": self.stdout_handle,
                }
            )
        else:
            for descriptor, target in ((self.stdin, 0), (self.stdout, 1)):
                if descriptor != target:
                    os.dup2(descriptor, target)
                    os.close(descriptor)


def run(server: Server, arguments: tuple[str, ...]) -> int:
    """Activate the validated server prefix and execute its stdio executable."""
    if server.stdio is None:
        raise CondaError("Only stdio servers can be launched.")
    server = server.revalidate()
    assert server.stdio is not None
    executable = server.resolve_executable()
    host = Path(sys.executable).resolve()
    _check_activation_paths(server.prefix, host, context.root_prefix)
    stdin = stdout = -1
    wrapper: Path | None = None
    process: subprocess.Popen[bytes] | _launch_windows._Process | None = None
    try:
        stdin = os.dup(0)
        stdout = os.dup(1)
        info = executable.stat()
        payload = LaunchPayload(
            (str(executable), *server.stdio.args, *arguments),
            tuple(item.name for item in server.stdio.environment if item.required),
            os.getcwd(),
            str(server.prefix),
            server.name,
            server.package,
            str(server.manifest),
            server.manifest_digest,
            str(executable),
            stdin=stdin,
            stdout=stdout,
            identity=(
                info.st_dev,
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            ),
        ).dump()
        wrapper, command = _activation_wrapper(server.prefix, host)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"BASH_ENV", "ENV"} and not key.startswith("_CONDA_MCP_")
        }
        environment[_PAYLOAD] = payload
        if on_win:
            process = _launch_windows.launch(command, environment, stdin, stdout)
        else:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=2,
                stderr=2,
                pass_fds=(stdin, stdout),
                start_new_session=True,
                env=environment,
            )
        return _wait_for_process(process)
    finally:
        for descriptor in (stdin, stdout):
            if descriptor >= 0:
                os.close(descriptor)
        if process is not None and process.poll() is None:
            _reap_after_interrupt(process, 2)
        if wrapper is not None:
            wrapper.unlink(missing_ok=True)


def _activation_wrapper(prefix: Path, host: Path) -> tuple[Path, list[str]]:
    """Generate and harden conda's native wrapper for a fixed trampoline argv."""
    wrapper, command = wrap_subprocess_call(
        context.root_prefix,
        str(prefix),
        False,
        False,
        (str(host), "-I", "-m", "conda_mcp._launch"),
    )
    path = Path(wrapper)
    try:
        _check_activation_paths(prefix, path)
        source = path.read_text(encoding="utf-8")
        if path.suffix == ".bat":
            lines = source.splitlines(keepends=True)
            activate = next(
                (
                    i
                    for i, line in enumerate(lines)
                    if line.removeprefix("@").startswith("CALL ")
                    and " activate " in line
                ),
                None,
            )
            launch_line = next(
                (
                    i
                    for i, line in enumerate(lines)
                    if "-I -m conda_mcp._launch" in line
                ),
                None,
            )
            if (
                activate is None
                or launch_line is None
                or launch_line <= activate
                or command[-2] != "/c"
            ):
                raise CondaError("Conda generated an unsupported activation wrapper.")
            deactivate = lines[activate].split(" activate ", 1)[0] + " deactivate\n"
            epilogue = (
                'set "_CONDA_MCP_EXIT=%ERRORLEVEL%"\n'
                + deactivate
                + "exit /b %_CONDA_MCP_EXIT%\n"
            )
            # Run deactivation hooks before returning the server's exit status.
            exit_line = next(
                (
                    i
                    for i in range(launch_line + 1, len(lines))
                    if lines[i].removeprefix("@").lower().startswith("exit /b")
                ),
                None,
            )
            if exit_line is None:
                raise CondaError("Conda generated an unsupported activation wrapper.")
            lines[launch_line + 1 : exit_line + 1] = [epilogue]
            path.write_text("".join(lines), encoding="utf-8")
            command = [command[0], "/d", "/v:off", *command[1:]]
        else:
            lines = source.splitlines(keepends=True)
            if (
                not lines
                or not lines[0].startswith('eval "$(')
                or "conda activate" not in source
            ):
                raise CondaError("Conda generated an unsupported activation wrapper.")
            lines[0] = "_conda_mcp_hook=" + lines[0][5:] + 'eval "$_conda_mcp_hook"\n'
            launch_line = next(
                (
                    i
                    for i, line in enumerate(lines)
                    if "-I -m conda_mcp._launch" in line
                ),
                None,
            )
            if launch_line is None:
                raise CondaError("Conda generated an unsupported activation wrapper.")
            lines.insert(launch_line, "set +e\n")
            path.write_text(
                "set -e\ntrap ':' INT TERM\n" + "".join(lines), encoding="utf-8"
            )
        return path, command
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _check_activation_paths(prefix: Path, *paths: Path | str) -> None:
    """Reject values native POSIX activation interpolates with unsafe quoting."""
    candidates = [prefix, Path(context.root_prefix)] + [
        Path(value)
        for key, value in os.environ.items()
        if value and (key == "CONDA_PREFIX" or key.startswith("CONDA_PREFIX_"))
    ]
    hooks = [
        hook
        for candidate in candidates
        for phase in ("activate", "deactivate")
        for hook in (candidate / "etc" / "conda" / f"{phase}.d").glob(
            "*.bat" if on_win else "*.sh"
        )
    ]
    values: tuple[Path | str | None, ...] = (
        prefix,
        *paths,
        os.environ.get("TMPDIR"),
        os.environ.get("TEMP"),
        os.environ.get("TMP"),
        os.environ.get("CONDA_EXE"),
        os.environ.get("CONDA_BAT"),
        *candidates,
        *hooks,
    )
    if any(
        value is not None
        and any(char in str(value) for char in ('%\r\n"^' if on_win else _UNSAFE_POSIX))
        for value in values
    ):
        raise CondaError("Unsafe path for conda activation.")


def _wait_for_process(
    process: subprocess.Popen[bytes] | _launch_windows._Process, grace: float = 2
) -> int:
    """Forward one terminating signal and bound process-group cleanup time."""
    interrupted: list[int] = []
    cleaned = False

    def forward(signum: int, _frame: object) -> None:
        if not interrupted:
            interrupted.append(signum)
            try:
                if on_win:
                    process.terminate()
                else:
                    os.killpg(process.pid, signum)
            except ProcessLookupError:
                pass

    handlers = {}
    primary: BaseException | None = None
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            handlers[sig] = signal.signal(sig, forward)
        while process.poll() is None:
            if interrupted:
                cleaned = on_win
                _reap_after_interrupt(process, grace)
                cleaned = True
            else:
                time.sleep(0.05)
        code = process.wait()
        return (
            128 + interrupted[0] if interrupted else (128 - code if code < 0 else code)
        )
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            if on_win:
                if not cleaned and (primary is not None or process.poll() is None):
                    try:
                        _reap_after_interrupt(process, grace)
                    except BaseException as cleanup:
                        if primary is None:
                            raise
                        primary.add_note(_cleanup_note("runner", cleanup))
            elif not cleaned:
                try:
                    if not interrupted:
                        os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                _reap_after_interrupt(process, grace)
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)


def _cleanup_note(operation: str, error: BaseException) -> str:
    code = getattr(error, "winerror", None) or getattr(error, "errno", None)
    detail = f" (code {code})" if isinstance(code, int) else ""
    return f"Windows {operation} cleanup: {type(error).__name__}{detail}"


def _reap_after_interrupt(
    process: subprocess.Popen[bytes] | _launch_windows._Process, grace: float
) -> None:
    """Kill only the wrapper's process group after its grace period expires."""
    if on_win:
        deadline = time.monotonic() + 5
        primary: BaseException | None = None
        try:
            process.kill()
        except BaseException as error:
            primary = error
        try:
            # Closing the job still kills descendants if explicit termination failed.
            cast(_launch_windows._Process, process)._conda_mcp_close_job()
        except BaseException as error:
            if primary is None:
                primary = error
            else:
                primary.add_note(_cleanup_note("job close", error))
        try:
            process.wait(timeout=max(0, deadline - time.monotonic()))
        except BaseException as error:
            if primary is None:
                primary = error
            else:
                primary.add_note(_cleanup_note("process reap", error))
        if primary is not None:
            raise primary
        return
    if process.pid == os.getpgrp():
        raise CondaError("Refusing to signal the caller's process group.")
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            process.wait(timeout=5)
            return
        process.poll()
        time.sleep(0.05)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)
