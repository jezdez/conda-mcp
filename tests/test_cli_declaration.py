"""Validate the declaration shipped for the built-in CLI server."""

from __future__ import annotations

from pathlib import Path

from conda_mcp.servers import discover

DECLARATION = Path(__file__).parents[1] / "recipe" / "conda-cli.json"


def test_shipped_declaration_is_discoverable(install_package) -> None:
    prefix = install_package(
        name="conda-mcp",
        files={"share/conda-mcp/servers/conda-cli.json": DECLARATION.read_bytes()},
    )

    (server,) = discover(prefix)

    assert server.name == "conda-cli"
    assert server.package == "conda-mcp"
    assert server.description
    assert server.stdio is not None
    assert server.stdio.command == "python"
    assert server.stdio.args == ("-I", "-m", "conda_mcp._stdio", "serve")
