from __future__ import annotations

import asyncio
import inspect
import json
import os
import select
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from conda import CondaError
from conda.common.compat import on_win
from pip._vendor.distlib.scripts import ScriptMaker

from conda_mcp.run import (
    LaunchPayload,
    _activation_wrapper,
    _check_activation_paths,
    _reap_after_interrupt,
    run,
)
from conda_mcp.servers import Server, discover

PROBE = Path(__file__).with_name("activation_probe.py")


def test_asyncio_subprocess_transport_receives_protocol_object():
    """Guard the private test-only cancellation hook used on Windows."""
    loop = asyncio.new_event_loop()
    try:
        signature = inspect.signature(loop._make_subprocess_transport)
        assert next(iter(signature.parameters)) == "protocol"
        source = inspect.getsource(asyncio.base_events.BaseEventLoop.subprocess_exec)
        assert "protocol = protocol_factory()" in source
        assert "self._make_subprocess_transport(\n            protocol," in source
    finally:
        loop.close()


def test_run_requires_a_stdio_server(tmp_path: Path):
    server = Server(
        name="http",
        description="HTTP",
        prefix=tmp_path,
        manifest=tmp_path / "server.json",
        manifest_digest="digest",
        package="provider",
        version="1",
        build="0",
        channel="test",
        stdio=None,
        http=None,
        registry_name=None,
    )

    with pytest.raises(Exception, match="stdio"):
        run(server, ())


@pytest.mark.skipif(on_win, reason="POSIX activation")
def test_run_preserves_literal_arguments_and_protocol_streams(
    install_package, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    output = tmp_path / "arguments"
    prefix = install_package(
        manifest={
            "schema_version": 1,
            "name": "probe",
            "description": "Probe",
            "stdio": {
                "command": "probe",
                "environment": [{"name": "MCP_EMPTY", "required": True}],
            },
        },
        files={
            "bin/probe": (b'#!/bin/sh\nprintf \'%s\\n\' "$@" > "$MCP_OUTPUT"\ncat\n'),
        },
    )
    executable = prefix / "bin/probe"
    executable.chmod(0o755)
    monkeypatch.setenv("MCP_EMPTY", "")
    monkeypatch.setenv("MCP_OUTPUT", str(output))
    [server] = discover(prefix)

    assert run(server, ("", "space value", "$(literal)", "line\nbreak")) == 0
    assert output.read_text(encoding="utf-8").splitlines() == [
        "",
        "space value",
        "$(literal)",
        "line",
        "break",
    ]


@pytest.mark.skipif(on_win, reason="POSIX activation")
def test_run_stops_when_activation_hook_fails(install_package, tmp_path: Path):
    prefix = install_package(
        manifest={
            "schema_version": 1,
            "name": "probe",
            "description": "Probe",
            "stdio": {"command": "probe"},
        },
        files={"bin/probe": b"#!/bin/sh\nexit 42\n"},
    )
    executable = prefix / "bin/probe"
    executable.chmod(0o755)
    hook = prefix / "etc/conda/activate.d/fail.sh"
    hook.parent.mkdir(parents=True)
    hook.write_text("return 17\n", encoding="utf-8")
    [server] = discover(prefix)

    assert run(server, ()) == 17


def test_trampoline_rejects_oversized_or_invalid_payload():
    with pytest.raises(ValueError, match="invalid launch payload"):
        LaunchPayload.decode("{}")
    with pytest.raises(ValueError, match="too large"):
        LaunchPayload.decode("x" * 65537)


@pytest.mark.skipif(on_win, reason="POSIX process groups")
def test_wait_kills_process_group_after_interrupt():
    process = subprocess.Popen(
        ["/bin/sh", "-c", "trap '' TERM; sleep 30"], start_new_session=True
    )
    try:
        _reap_after_interrupt(process, grace=0.01)
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


@pytest.mark.skipif(on_win, reason="POSIX process groups")
def test_interrupt_never_signals_the_callers_process_group(monkeypatch):
    from types import SimpleNamespace

    sent = []
    monkeypatch.setattr(os, "killpg", lambda *args: sent.append(args))
    with pytest.raises(CondaError, match="caller's process group"):
        _reap_after_interrupt(SimpleNamespace(pid=os.getpgrp()), grace=0)
    assert sent == []


@pytest.mark.skipif(on_win, reason="POSIX process groups")
def test_reap_waits_without_sigkill_when_process_group_has_exited(
    monkeypatch: pytest.MonkeyPatch,
):
    class Process:
        pid = 123
        waited = False

        def wait(self, *, timeout: float) -> int:
            assert timeout == 5
            self.waited = True
            return 0

        def poll(self) -> None:
            return None

    process = Process()
    signals: list[int] = []

    def killpg(pid: int, sig: int) -> None:
        assert pid == process.pid
        signals.append(sig)
        raise ProcessLookupError

    monkeypatch.setattr(os, "killpg", killpg)

    _reap_after_interrupt(process, grace=0.01)

    assert signals == [0]
    assert process.waited


@pytest.fixture
def executable_server(install_package):
    """Install a recorded interpreter wrapper and a real protocol test server."""
    fixture = Path(__file__).with_name("fixtures") / "stdio_server.py"
    relative = "Scripts/example.exe" if on_win else "bin/python"
    prefix = install_package(
        manifest={
            "schema_version": 1,
            "name": "example",
            "description": "Example",
            "stdio": {
                "command": "example.exe" if on_win else "python",
                "args": [] if on_win else [str(fixture)],
                "environment": [{"name": "MCP_TEST_TOKEN", "required": True}],
            },
        },
        files={relative: b""},
    )
    executable = prefix / relative
    if on_win:
        executable.unlink()
        source = prefix / "source"
        source.mkdir()
        (source / "example.py").write_bytes(b"#!python\n" + fixture.read_bytes())
        maker = ScriptMaker(str(source), str(executable.parent))
        maker.executable = sys.executable
        maker.variants = {""}
        maker.make("example.py")
    else:
        executable.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        executable.chmod(0o755)
    return prefix


def test_protocol_streams_before_exit_and_receives_eof(executable_server):
    process = subprocess.Popen(
        [sys.executable, "-I", str(PROBE), str(executable_server)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "MCP_TEST_TOKEN": ""},
    )
    try:
        assert process.stdout.readline() == b"READY\n"
        assert process.poll() is None
        stdout, stderr = process.communicate(b'{"literal": "protocol"}\n', timeout=15)
        assert process.returncode == 0, stderr
        assert stdout == b'{"literal": "protocol"}\nEOF\n'
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


def test_run_ignores_unrelated_invalid_declaration(
    executable_server: Path, install_package
) -> None:
    install_package(
        "broken",
        files={"share/conda-mcp/servers/broken.json": b"{}"},
    )
    result = subprocess.run(
        [sys.executable, "-I", str(PROBE), str(executable_server)],
        input=b"PROTOCOL\n",
        capture_output=True,
        timeout=30,
        env={**os.environ, "MCP_TEST_TOKEN": ""},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == b"READY\nPROTOCOL\nEOF\n"


def test_direct_run_keeps_plugin_output_off_protocol(
    executable_server: Path, noisy_conda_venv: Path
) -> None:
    completed = subprocess.run(
        [
            str(noisy_conda_venv),
            "-I",
            "-m",
            "conda_mcp._stdio",
            "run",
            "-p",
            str(executable_server),
            "--package",
            "provider",
            "example",
        ],
        input=b"PROTOCOL\n",
        capture_output=True,
        timeout=30,
        env={
            **os.environ,
            "MCP_TEST_TOKEN": "",
            # Activation scripts belong to the conda install, not the test venv.
            "CONDA_ROOT_PREFIX": sys.prefix,
        },
    )

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert completed.stdout == b"READY\nPROTOCOL\nEOF\n"
    assert b"NOISY_CONDA_PLUGIN" not in completed.stdout
    assert b"NOISY_CONDA_PLUGIN" in completed.stderr


@pytest.mark.skipif(on_win, reason="POSIX deactivation script")
def test_exit_status_survives_deactivation_and_argv_is_literal(
    executable_server, tmp_path
):
    arguments = ["", "two words", "$() `touch NEVER`", "new\nline"]
    deactivation = executable_server / "etc/conda/deactivate.d/last.sh"
    deactivation.parent.mkdir(parents=True)
    deactivation.write_text("printf 'DEACTIVATE\\n'\nreturn 19\n")
    result = subprocess.run(
        [sys.executable, "-I", str(PROBE), str(executable_server), *arguments],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        env={
            **os.environ,
            "MCP_TEST_TOKEN": "",
            "MCP_TEST_MODE": "metadata",
            "MCP_TEST_EXIT": "7",
        },
    )
    assert result.returncode == 7, result.stderr
    document = json.loads(result.stdout)
    assert document["argv"] == arguments
    assert document["cwd"] == str(tmp_path)
    assert document["reserved"] is False and document["token"] == ""
    assert "DEACTIVATE" in result.stderr
    assert not (tmp_path / "NEVER").exists()


def test_missing_required_variable_fails_without_protocol_output(executable_server):
    environment = dict(os.environ)
    environment.pop("MCP_TEST_TOKEN", None)
    result = subprocess.run(
        [sys.executable, "-I", str(PROBE), str(executable_server)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode != 0 and result.stdout == ""
    assert "MCP_TEST_TOKEN" in result.stderr


@pytest.mark.skipif(on_win, reason="POSIX activation script")
def test_noisy_activation_cannot_consume_protocol_input(executable_server):
    hook = executable_server / "etc/conda/activate.d/noisy.sh"
    hook.parent.mkdir(parents=True)
    hook.write_text(
        "printf 'NOISY STDOUT\\n'\nprintf 'NOISY STDERR\\n' >&2\n"
        "if read line; then printf 'STOLE INPUT\\n'; fi\nexport MCP_TEST_TOKEN=''\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", str(PROBE), str(executable_server)],
        input="PROTOCOL\n",
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "READY\nPROTOCOL\nEOF\n"
    assert "NOISY STDOUT" in result.stderr and "NOISY STDERR" in result.stderr
    assert "STOLE INPUT" not in result.stderr


@pytest.mark.skipif(on_win, reason="POSIX native process-group cleanup")
def test_repeated_signals_terminate_ignoring_descendants(executable_server, tmp_path):
    pid_file = tmp_path / "child.pid"
    process = subprocess.Popen(
        [sys.executable, "-I", str(PROBE), str(executable_server)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            **os.environ,
            "MCP_TEST_TOKEN": "",
            "MCP_TEST_MODE": "tree",
            "MCP_TEST_CHILD_PID": str(pid_file),
        },
    )
    try:
        assert select.select([process.stdout], [], [], 15)[0]
        child_pid = json.loads(process.stdout.readline())["child"]
        process.send_signal(signal.SIGTERM)
        process.send_signal(signal.SIGTERM)
        _, stderr = process.communicate(timeout=8)
        assert process.returncode == 128 + signal.SIGTERM, stderr
        result = subprocess.run(
            ["ps", "-p", str(child_pid), "-o", "stat="], capture_output=True, text=True
        )
        assert not result.stdout.strip() or result.stdout.strip().startswith("Z")
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


@pytest.mark.skipif(on_win, reason="POSIX activation scripts")
@pytest.mark.parametrize("replacement", ["manifest", "provider", "executable"])
def test_activation_cannot_replace_selected_inputs(executable_server, replacement):
    hook = executable_server / "etc/conda/activate.d/replace.sh"
    hook.parent.mkdir(parents=True)
    if replacement == "manifest":
        hook.write_text(
            'printf "{}" > "$CONDA_PREFIX/share/conda-mcp/servers/example.json"\n'
        )
    elif replacement == "provider":
        hook.write_text('rm "$CONDA_PREFIX/conda-meta/provider-1-0.json"\n')
    else:
        hook.write_text(
            'printf "#!/bin/sh\\nprintf STOLEN\\n" > "$CONDA_PREFIX/bin/python"\n'
        )
    result = subprocess.run(
        [sys.executable, "-I", str(PROBE), str(executable_server)],
        env={**os.environ, "MCP_TEST_TOKEN": ""},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode != 0 and result.stdout == "", result.stderr
    assert "STOLEN" not in result.stderr


@pytest.mark.skipif(on_win, reason="POSIX activation quoting")
@pytest.mark.parametrize(
    "name",
    [
        'danger"file.sh',
        "danger$(touch MARKER).sh",
        "danger`touch MARKER`.sh",
        "new\nline.sh",
    ],
)
def test_activation_hook_paths_never_get_shell_evaluated(
    executable_server, tmp_path, name
):
    hook = executable_server / "etc/conda/activate.d" / name
    hook.parent.mkdir(parents=True)
    hook.write_text("export MCP_TEST_TOKEN=ok\n")
    result = subprocess.run(
        [sys.executable, "-I", str(PROBE), str(executable_server)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode != 0 and result.stdout == ""
    assert "Unsafe path" in result.stderr and not (tmp_path / "MARKER").exists()


def test_unsafe_native_override_paths_are_rejected(tmp_path, monkeypatch):
    for name in ("CONDA_EXE", "TMPDIR", "CONDA_BAT", "CONDA_PREFIX"):
        with monkeypatch.context() as patch:
            patch.setenv(name, "unsafe%path\n" if on_win else "unsafe$(path)")
            with pytest.raises(Exception, match="Unsafe path"):
                _check_activation_paths(tmp_path)


def test_stacked_activation_paths_are_validated_before_wrapper_generation(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CONDA_PREFIX_1", "unsafe%path\n" if on_win else "unsafe$(path)")
    with pytest.raises(Exception, match="Unsafe path"):
        _check_activation_paths(tmp_path)


def test_host_module_launch_ignores_ambient_pythonpath(executable_server, tmp_path):
    poison = tmp_path / "poison"
    poison.mkdir()
    (poison / "conda_mcp.py").write_text("raise RuntimeError('POISON MODULE')\n")
    before = dict(os.environ)
    result = subprocess.run(
        [sys.executable, "-I", str(PROBE), str(executable_server)],
        env={
            **os.environ,
            "PYTHONPATH": str(poison),
            "MCP_TEST_TOKEN": "",
            "MCP_TEST_MODE": "metadata",
        },
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "POISON" not in result.stdout + result.stderr
    assert json.loads(result.stdout)["prefix"] == str(executable_server)
    assert dict(os.environ) == before


def test_native_batch_wrapper_suppresses_autorun_and_checks_exit(tmp_path, monkeypatch):
    def native_wrapper(*args, **kwargs):
        wrapper = tmp_path / "native.bat"
        wrapper.write_text(
            '@echo off\nCALL "C:\\Conda\\condabin\\conda.bat" activate prefix\n'
            "python -I -m conda_mcp._launch\n"
            "IF %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%\nexit /b 0\n"
        )
        return str(wrapper), ["cmd.exe", "/c", str(wrapper)]

    monkeypatch.setattr("conda_mcp.run.wrap_subprocess_call", native_wrapper)
    wrapper, command = _activation_wrapper(tmp_path, Path(sys.executable))
    assert command[1:4] == ["/d", "/v:off", "/c"]
    assert 'set "_CONDA_MCP_EXIT=%ERRORLEVEL%"' in wrapper.read_text()
    assert 'CALL "C:\\Conda\\condabin\\conda.bat" deactivate' in wrapper.read_text()
    assert "exit /b %_CONDA_MCP_EXIT%" in wrapper.read_text()


@pytest.mark.parametrize(
    ("suffix", "source", "command"),
    [
        (".bat", "python -I -m conda_mcp._launch\nexit /b 0\n", ["cmd.exe", "/c"]),
        (".bat", "CALL conda.bat activate prefix\nexit /b 0\n", ["cmd.exe", "/c"]),
        (
            ".bat",
            "CALL conda.bat activate prefix\npython -I -m conda_mcp._launch\n",
            ["cmd.exe", "/c"],
        ),
        (
            ".bat",
            "CALL conda.bat activate prefix\n"
            "python -I -m conda_mcp._launch\nexit /b 0\n",
            ["cmd.exe", "/k"],
        ),
        (".sh", "conda activate prefix\npython -I -m conda_mcp._launch\n", ["bash"]),
        (".sh", 'eval "$(conda shell.posix hook)"\nconda activate prefix\n', ["bash"]),
    ],
)
def test_unsupported_activation_wrapper_is_removed(
    tmp_path, monkeypatch, suffix, source, command
):
    wrapper = tmp_path / ("wrapper" + suffix)
    wrapper.write_text(source)
    monkeypatch.setattr(
        "conda_mcp.run.wrap_subprocess_call",
        lambda *args: (str(wrapper), [*command, str(wrapper)]),
    )
    with pytest.raises(CondaError, match="unsupported activation wrapper"):
        _activation_wrapper(tmp_path, Path(sys.executable))
    assert not wrapper.exists()


def test_conda_batch_wrapper_preserves_activation_and_deactivates(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("conda.utils.on_win", True)
    monkeypatch.setattr("conda.utils.get_comspec", lambda: "cmd.exe")
    wrapper, command = _activation_wrapper(tmp_path, Path(sys.executable))
    try:
        source = wrapper.read_text(encoding="utf-8")
        assert "/d" in command and "/v:off" in command
        assert "@CALL " in source and " activate " in source
        assert "@IF %ERRORLEVEL% NEQ 0 EXIT /b %ERRORLEVEL%" in source
        assert source.index("-I -m conda_mcp._launch") < source.index(" deactivate")
        assert source.endswith("exit /b %_CONDA_MCP_EXIT%\n")
    finally:
        wrapper.unlink()


@pytest.mark.skipif(not on_win, reason="native Windows activation")
def test_windows_failing_activation_never_executes_server(executable_server):
    hook = executable_server / "etc/conda/activate.d/fail.bat"
    hook.parent.mkdir(parents=True)
    hook.write_text("@echo off\nexit /b 17\n")
    result = subprocess.run(
        [sys.executable, "-I", str(PROBE), str(executable_server)],
        env={**os.environ, "MCP_TEST_TOKEN": "present"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0 and result.stdout == ""
    assert "Activation script" in result.stderr


@pytest.mark.skipif(not on_win, reason="native Windows activation")
def test_windows_activation_preserves_protocol_bytes_and_literal_arguments(
    executable_server,
):
    hook = executable_server / "etc/conda/activate.d/noisy.bat"
    hook.parent.mkdir(parents=True)
    hook.write_text(
        "@echo off\necho ACTIVATION STDOUT\necho ACTIVATION STDERR 1>&2\n"
        'set /p ignored=\nset "MCP_TEST_TOKEN=activated"\nexit /b 0\n',
        encoding="utf-8",
    )
    protocol = b'{"literal": "snowman \\u2603"}\n'
    result = subprocess.run(
        [sys.executable, "-I", str(PROBE), str(executable_server)],
        input=protocol,
        capture_output=True,
        timeout=30,
        env={**os.environ, "MCP_TEST_TOKEN": "present"},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == b"READY\n" + protocol + b"EOF\n"
    assert b"ACTIVATION STDOUT" in result.stderr
    assert b"ACTIVATION STDERR" in result.stderr

    arguments = ["", "two words", "snowman \u2603", "$(literal) & ^"]
    metadata = subprocess.run(
        [sys.executable, "-I", str(PROBE), str(executable_server), *arguments],
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "MCP_TEST_TOKEN": "present",
            "MCP_TEST_MODE": "metadata",
        },
    )
    assert metadata.returncode == 0, metadata.stderr
    assert json.loads(metadata.stdout)["argv"] == arguments
    assert json.loads(metadata.stdout)["token"] == "activated"
