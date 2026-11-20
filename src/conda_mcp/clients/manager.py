"""Select a native adapter and construct the exact-owner conda launch command."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from conda import CondaError

from . import ClientAdapter, claude_code, claude_desktop, codex, copilot, cursor, kilo
from .config import ConfigTarget, Connection

if TYPE_CHECKING:
    from ..servers import Server


claude_code_adapter = claude_code.ClaudeCodeAdapter()

CLIENTS: dict[str, ClientAdapter] = {
    "claude-code": claude_code_adapter,
    "copilot": copilot.CopilotAdapter(claude_code_adapter),
    "codex": codex.CodexAdapter(),
    "kilo": kilo.KiloAdapter(),
    "claude-desktop": claude_desktop.ClaudeDesktopAdapter(),
    "cursor": cursor.CursorAdapter(),
}


def config_target(client: str, root: Path, *, global_scope: bool) -> ConfigTarget:
    """Keep explicit source-independent destination selection in one place."""
    try:
        if client not in CLIENTS:
            raise ValueError("Unsupported client.")
        if not global_scope and root.resolve() == Path.home().resolve():
            raise ValueError("Refusing to modify home without --global.")
        adapter = CLIENTS[client]
        path = adapter.destination(root, global_scope=global_scope)
        if not path.is_absolute():
            raise ValueError("Client configuration destination must be absolute.")
        return ConfigTarget(client, path, adapter.key, global_scope, adapter)
    except ValueError as error:
        raise CondaError(str(error)) from error


def render_entry(server: Server, target: ConfigTarget) -> dict[str, object]:
    """Translate package declarations into native input without reading secrets."""
    try:
        if server.stdio is not None:
            if not server.prefix.is_absolute():
                raise ValueError("Launch paths must be absolute.")
            connection = Connection(
                server.name,
                command=(
                    sys.executable,
                    "-I",
                    "-m",
                    "conda",
                    "mcp",
                    "run",
                    "-p",
                    str(server.prefix),
                    "--package",
                    server.package,
                    server.name,
                ),
                environment=tuple(item.name for item in server.stdio.environment),
            )
        else:
            http = server.http
            connection = Connection(
                server.name,
                url=http.url if http else None,
                bearer=http.bearer_token_env if http else None,
                headers=http.header_env if http else (),
            )
        return CLIENTS[target.client].render(
            connection, global_scope=target.global_scope
        )
    except ValueError as error:
        raise CondaError(str(error)) from error
