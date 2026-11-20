from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize("name", ["use-a-server", "inspect"])
def test_recordings_use_disposable_prefixes_and_project_scope(name):
    """Keep recordings out of named environments and user client configuration."""
    demos = Path(__file__).parents[1] / "demos"
    tape = (demos / f"{name}.tape").read_text(encoding="utf-8")
    assert "source demos/setup.sh" in tape
    assert "-p ../servers" in tape
    assert "--global" not in tape
    assert " -n " not in tape
    assert "conda mcp run" not in tape

    setup = (demos / "setup.sh").read_text(encoding="utf-8")
    for setting in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "APPDATA", "CONDARC"):
        assert f"export {setting}=" in setup
    assert "mktemp -d /tmp/mcp-demo.XXXXXX" in setup
    assert '--prefix "$DEMO_ROOT/tools"' in setup
    assert '--prefix "$DEMO_ROOT/servers"' in setup
    assert 'cd "$DEMO_ROOT/project"' in setup


def test_live_recording_uses_existing_fastmcp_client():
    """Only the live tape uses a client to execute the rendered server entry."""
    demos = Path(__file__).parents[1] / "demos"
    tape = (demos / "live-mcp.tape").read_text(encoding="utf-8")

    assert 'Type "# Live MCP session: launch, list tools, and call greet"' in tape
    assert "conda mcp render -p ../servers fastmcp-example --client claude-code" in tape
    assert "../servers/bin/fastmcp list server.json --timeout 30" in tape
    assert (
        "../servers/bin/fastmcp call server.json greet name=Conda --timeout 30" in tape
    )
    for name in ("use-a-server", "inspect"):
        passive = (demos / f"{name}.tape").read_text(encoding="utf-8")
        assert "fastmcp list" not in passive
        assert "fastmcp call" not in passive
