"""Claude Code native paths and portable MCP entries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import ClientAdapter

if TYPE_CHECKING:
    from .config import Connection


@dataclass(frozen=True)
class ClaudeCodeAdapter(ClientAdapter):
    """Claude Code destination and native connection rendering."""

    key: str = "mcpServers"

    def destination(self, root: Path, *, global_scope: bool) -> Path:
        """Select the user file or shared project .mcp.json."""
        return Path.home() / ".claude.json" if global_scope else root / ".mcp.json"

    def render(
        self, connection: Connection, *, global_scope: bool
    ) -> dict[str, object]:
        """Render an entry without changing Claude trust or approval settings."""
        if connection.name in {"workspace", "claude-in-chrome", "computer-use"}:
            raise ValueError("Server name is reserved by Claude Code.")
        if connection.command is not None:
            return {"type": "stdio", **connection.stdio()}
        return {"type": "http", **connection.http("${{{}}}")}
