"""Claude Desktop's global-only, local stdio file configuration."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import ClientAdapter

if TYPE_CHECKING:
    from .config import Connection


@dataclass(frozen=True)
class ClaudeDesktopAdapter(ClientAdapter):
    """Claude Desktop destination and local stdio rendering."""

    key: str = "mcpServers"

    def destination(self, root: Path, *, global_scope: bool) -> Path:
        """Resolve the documented native file without inventing project scope."""
        if not global_scope:
            raise ValueError("Claude Desktop requires --global.")
        home = Path.home()
        paths = {
            "darwin": home / "Library/Application Support/Claude",
            "win32": Path(os.environ.get("APPDATA") or home / "AppData/Roaming")
            / "Claude",
            "linux": home / ".config/Claude",
        }
        if sys.platform not in paths:
            raise ValueError("Unsupported Claude Desktop platform.")
        return paths[sys.platform] / "claude_desktop_config.json"

    def render(
        self, connection: Connection, *, global_scope: bool
    ) -> dict[str, object]:
        """Reject remote connectors, which are outside Desktop's stdio config file."""
        if connection.command is None:
            raise ValueError("Claude Desktop file configuration supports stdio only.")
        return connection.stdio()
