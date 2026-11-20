"""Cursor project/user configuration and credential reference syntax."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import ClientAdapter

if TYPE_CHECKING:
    from .config import Connection


@dataclass(frozen=True)
class CursorAdapter(ClientAdapter):
    """Cursor destination and native credential reference rendering."""

    key: str = "mcpServers"

    def destination(self, root: Path, *, global_scope: bool) -> Path:
        """Select the explicit project or home .cursor directory."""
        return (Path.home() if global_scope else root) / ".cursor/mcp.json"

    def render(
        self, connection: Connection, *, global_scope: bool
    ) -> dict[str, object]:
        """Use Cursor's inherited stdio environment and native HTTP placeholders."""
        if connection.command is not None:
            return {"type": "stdio", **connection.stdio()}
        return connection.http("${{env:{}}}")
