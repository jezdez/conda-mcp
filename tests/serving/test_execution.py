from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from conda_mcp.serving.execution import CompletionQueryError, CondaExecutor

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
