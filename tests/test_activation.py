import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conda import utils as conda_utils
from conda.common.compat import on_win

from conda_mcp.run import _activation_wrapper


@pytest.mark.skipif(on_win, reason="POSIX activation")
def test_activated_server_keeps_hook_output_off_protocol(tmp_path):
    prefix = tmp_path / "server prefix"
    meta = prefix / "conda-meta"
    meta.mkdir(parents=True)
    (meta / "history").touch()
    for phase in ("activate", "deactivate"):
        hooks = prefix / "etc" / "conda" / f"{phase}.d"
        hooks.mkdir(parents=True)
        (hooks / "probe.sh").write_text(f"echo {phase}-noise\nexport MCP_PROBE=1\n")
    binary = prefix / "bin"
    binary.mkdir()
    (binary / "probe").write_text('#!/bin/sh\nexec /bin/cat "$@"\n')
    (binary / "probe").chmod(0o755)
    (meta / "probe-1-0.json").write_text(
        json.dumps(
            {
                "name": "probe",
                "version": "1",
                "build": "0",
                "build_number": 0,
                "files": ["bin/probe", "share/conda-mcp/servers/probe.json"],
                "channel": "local",
                "subdir": "noarch",
                "fn": "probe-1-0.conda",
                "url": "file:///probe-1-0.conda",
            }
        )
    )
    manifest = prefix / "share/conda-mcp/servers/probe.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "probe",
                "description": "Probe",
                "stdio": {
                    "command": "probe",
                    "environment": [{"name": "MCP_PROBE", "required": True}],
                },
            }
        ),
        encoding="utf-8",
    )
    harness = Path(__file__).with_name("activation_probe.py")
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("CONDA_")
    }
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(harness.parents[1] / "src"), env.get("PYTHONPATH")])
    )
    env["MCP_TEST_SERVER_NAME"] = "probe"
    result = subprocess.run(
        [sys.executable, str(harness), str(prefix)],
        check=False,
        input=b"protocol\n",
        capture_output=True,
        env=env,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == b"protocol\n"
    assert b"activate-noise" in result.stderr
    assert b"deactivate-noise" in result.stderr


@pytest.mark.skipif(on_win, reason="simulates Windows activation on POSIX")
def test_activation_wrapper_accepts_condas_native_batch_wrapper(tmp_path, monkeypatch):
    monkeypatch.setattr(conda_utils, "on_win", True)
    monkeypatch.setattr(conda_utils, "get_comspec", lambda: "cmd.exe")

    wrapper, command = _activation_wrapper(tmp_path / "prefix", Path(sys.executable))

    source = wrapper.read_text(encoding="utf-8")
    assert '@CALL "' in source
    assert command[1:4] == ["/d", "/v:off", "/d"]
    assert command[-2:] == ["/c", str(wrapper)]
    assert 'set "_CONDA_MCP_EXIT=%ERRORLEVEL%"' in source
    assert "exit /b %_CONDA_MCP_EXIT%" in source
