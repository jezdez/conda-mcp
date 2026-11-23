"""Exercise the installed MCP server over real stdio."""

from __future__ import annotations

import shutil
import subprocess

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.anyio
async def test_serve_initializes_and_calls_a_read_only_tool() -> None:
    conda = shutil.which("conda")
    if conda is None:
        pytest.skip("conda is not installed")

    parameters = StdioServerParameters(command=conda, args=["mcp", "serve"])

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
    assert result.is_error is False
    assert result.content
    assert "generated_tools" in capabilities.contents[0].text


def test_disabled_plugins_do_not_start_a_server() -> None:
    conda = shutil.which("conda")
    if conda is None:
        pytest.skip("conda is not installed")

    completed = subprocess.run(
        [conda, "--no-plugins", "mcp", "serve"],
        input=b"",
        capture_output=True,
        timeout=120,
    )

    assert completed.returncode != 0
    assert b"jsonrpc" not in completed.stdout
