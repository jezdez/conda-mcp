"""Codex native TOML destinations and name-based environment references."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import ClientAdapter

if TYPE_CHECKING:
    from .config import Connection


@dataclass(frozen=True)
class CodexAdapter(ClientAdapter):
    """Codex destination and name-based environment reference rendering."""

    key: str = "mcp_servers"

    def destination(self, root: Path, *, global_scope: bool) -> Path:
        """Respect CODEX_HOME for user configuration only."""
        base = (
            Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
            if global_scope
            else root / ".codex"
        )
        return base / "config.toml"

    def render(
        self, connection: Connection, *, global_scope: bool
    ) -> dict[str, object]:
        """Forward variable names through native Codex fields, never their values."""
        if connection.command is not None:
            entry = connection.stdio()
            if connection.environment:
                entry["env_vars"] = list(connection.environment)
            return entry
        if connection.url is None:
            raise ValueError("Server has no declared transport.")
        entry = {"url": connection.url}
        if connection.bearer:
            entry["bearer_token_env_var"] = connection.bearer
        if connection.headers:
            entry["env_http_headers"] = dict(connection.headers)
        return entry
