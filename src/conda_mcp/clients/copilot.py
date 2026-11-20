"""GitHub Copilot portable project and user MCP configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import ClientAdapter
from .claude_code import ClaudeCodeAdapter

if TYPE_CHECKING:
    from .config import Connection


@dataclass(frozen=True)
class CopilotAdapter(ClientAdapter):
    """Copilot destination and portable MCP rendering."""

    claude_code: ClaudeCodeAdapter
    key: str = "mcpServers"

    def destination(self, root: Path, *, global_scope: bool) -> Path:
        """Respect COPILOT_HOME only in explicitly selected user scope."""
        if global_scope:
            return (
                Path(os.environ.get("COPILOT_HOME") or Path.home() / ".copilot")
                / "mcp-config.json"
            )
        return root / ".mcp.json"

    def render(
        self, connection: Connection, *, global_scope: bool
    ) -> dict[str, object]:
        """Honor Claude Code's restrictions in the shared project file."""
        if not global_scope:
            return self.claude_code.render(connection, global_scope=False)
        if connection.command is not None:
            return {"type": "stdio", **connection.stdio()}
        return {"type": "http", **connection.http("${{{}}}")}
