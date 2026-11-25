from __future__ import annotations

import json

import pytest
from mcp import Client

from conda_mcp.serving.cli import serve
from conda_mcp.serving.execution import CondaExecutor
from conda_mcp.serving.server import CAPABILITIES_URI, CondaMCPServer


@pytest.mark.anyio
async def test_plugin_metadata_failure_serves_diagnostics_without_tools(monkeypatch):
    async def fail(_self):
        raise RuntimeError("broken metadata")

    documents = []

    async def inspect(server):
        async with Client(server.server) as client:
            resource = await client.read_resource(CAPABILITIES_URI)
            documents.append(json.loads(resource.contents[0].text))
            assert (await client.list_tools()).tools == []

    monkeypatch.setattr(CondaExecutor, "discover_plugin_state", fail)
    monkeypatch.setattr(CondaMCPServer, "run_stdio", inspect)
    await serve(CondaExecutor.from_environment())

    assert documents[0]["plugins"] == []
    assert documents[0]["catalog"]["root"] is not None
    assert any(
        item["reason"] == "broken metadata"
        for item in documents[0]["catalog"]["diagnostics"]
    )
