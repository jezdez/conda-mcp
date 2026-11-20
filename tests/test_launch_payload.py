from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from conda_mcp import _launch
from conda_mcp.run import LaunchPayload
from conda_mcp.servers import discover


@pytest.fixture
def payload(tmp_path):
    return LaunchPayload(
        argv=(str(tmp_path / "bin/example"), "", "two words\nthree"),
        required=(),
        cwd=str(tmp_path),
        prefix=str(tmp_path),
        name="example",
        package="provider",
        manifest=str(tmp_path / "share/conda-mcp/servers/example.json"),
        digest="a" * 64,
        executable=str(tmp_path / "bin/example"),
        identity=(1, 2, 3, 4, 5),
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("prefix", "relative"),
        ("stdin", True),
        ("stdout", -1),
        ("digest", "bad"),
        ("argv", ["\0"]),
        ("required", ["BAD NAME"]),
        ("executable", "relative"),
        ("package", None),
        ("name", "../example"),
    ],
)
def test_payload_rejects_invalid_field_values(payload, key, value):
    data = asdict(payload)
    data[key] = value
    with pytest.raises(ValueError):
        LaunchPayload.decode(json.dumps(data))


def test_payload_rejects_duplicate_keys_and_oversize_input(payload):
    encoded = payload.dump()
    with pytest.raises(ValueError):
        LaunchPayload.decode(encoded[:-1] + ',"stdin":42}')
    with pytest.raises(ValueError):
        LaunchPayload.decode(encoded + " " * 65536)


def test_payload_handles_windows_raw_handles_without_treating_them_as_fds(payload):
    data = asdict(payload)
    data.update(stdin_handle=101, stdout_handle=202)
    decoded = LaunchPayload.decode(json.dumps(data))
    assert decoded.stdin_handle == 101 and decoded.stdout_handle == 202


def test_launch_payload_owns_activated_revalidation(install_package, monkeypatch):
    relative = "Scripts/example.exe" if os.name == "nt" else "bin/example"
    prefix = install_package(
        manifest={
            "schema_version": 1,
            "name": "example",
            "description": "Example",
            "stdio": {"command": "example"},
        },
        files={relative: b"#!/bin/sh\nexit 0\n"},
    )
    executable = prefix / relative
    executable.chmod(0o755)
    server = discover(prefix)[0]
    stat = executable.stat()
    payload = LaunchPayload(
        argv=(str(executable),),
        required=(),
        cwd=str(prefix),
        prefix=str(prefix),
        name=server.name,
        package=server.package,
        manifest=str(server.manifest),
        digest=server.manifest_digest,
        executable=str(executable),
        identity=(
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        ),
    )
    monkeypatch.setenv("CONDA_PREFIX", str(prefix))
    assert payload.revalidate() == executable
    monkeypatch.setenv("CONDA_PREFIX", str(prefix / "wrong"))
    with pytest.raises(Exception, match="activation"):
        payload.revalidate()


def test_windows_trampoline_waits_for_server_instead_of_exec_overlay(
    monkeypatch, tmp_path
):
    calls = []
    payload = SimpleNamespace(
        argv=("recorded-server.exe", "two words"),
        cwd=str(tmp_path),
        revalidate=lambda: "recorded-server.exe",
        restore_protocol=lambda: calls.append("restored"),
    )
    monkeypatch.setenv("_CONDA_MCP_LAUNCH", "payload")
    monkeypatch.setattr(_launch.LaunchPayload, "decode", lambda value: payload)
    monkeypatch.setattr(
        _launch,
        "os",
        SimpleNamespace(
            name="nt",
            environ=os.environ,
            chdir=lambda cwd: calls.append(cwd),
            execve=lambda *args: calls.append("incorrect overlay"),
        ),
    )

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return subprocess.CompletedProcess(arguments, 7)

    monkeypatch.setattr(subprocess, "run", run)
    assert _launch.main() == 7
    assert calls == [
        "restored",
        str(tmp_path),
        (payload.argv, {"executable": "recorded-server.exe", "check": False}),
    ]
