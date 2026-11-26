"""Exercise the installed MCP server over real stdio."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_direct_serve_keeps_plugin_output_off_protocol(
    noisy_conda_venv: Path,
) -> None:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    completed = subprocess.run(
        [str(noisy_conda_venv), "-I", "-m", "conda_mcp._stdio", "serve"],
        input=json.dumps(request).encode() + b"\n",
        capture_output=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert b"NOISY_CONDA_PLUGIN" in completed.stderr
    assert b"NOISY_CONDA_PLUGIN" not in completed.stdout
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    assert responses[0]["id"] == 1
    assert "result" in responses[0]


@pytest.mark.anyio
async def test_serve_initializes_and_calls_a_read_only_tool() -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-I", "-m", "conda", "mcp", "serve"],
        env={
            name: os.environ[name]
            for name in ("COVERAGE_PROCESS_CONFIG",)
            if name in os.environ
        },
    )

    with anyio.fail_after(300):
        async with (
            stdio_client(parameters) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = {tool.name for tool in (await session.list_tools()).tools}
            result = await session.call_tool("conda_info", {"json": True})
            capabilities = await session.read_resource("conda://capabilities")

    assert "conda_info" in tools
    assert "conda_execute" not in tools
    assert "conda_mcp_serve" not in tools
    assert "conda_mcp_run" not in tools
    assert result.is_error is False
    assert result.content
    assert "generated_tools" in capabilities.contents[0].text


def test_disabled_plugins_do_not_start_a_server() -> None:
    completed = subprocess.run(
        [sys.executable, "-I", "-m", "conda", "--no-plugins", "mcp", "serve"],
        input=b"",
        capture_output=True,
        timeout=120,
    )

    assert completed.returncode != 0
    assert b"jsonrpc" not in completed.stdout
    assert b"invalid choice: 'mcp'" in completed.stderr
