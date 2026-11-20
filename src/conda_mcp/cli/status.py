"""Report client registration state."""

from __future__ import annotations

from pathlib import Path

from conda.base.context import context

from ..clients.manager import CLIENTS, config_target
from ..registrations import registration
from .output import message, structured, table


def execute(args) -> int:
    """Inspect each selected configuration file once."""
    targets = [
        config_target(client, Path.cwd(), global_scope=args.global_scope)
        for client in ([args.client] if args.client else CLIENTS)
        if client != "claude-desktop" or args.global_scope or args.client
    ]
    result = []
    seen = set()
    for target in targets:
        if target.path not in seen:
            result.extend(registration(target))
            seen.add(target.path)
    if context.json:
        structured(result)
    elif result:
        table(
            ("Server", "Clients", "Registration", "Source", "Effective", "Path"),
            (
                (
                    row["name"],
                    ", ".join(row["shared_clients"]),
                    row["state"],
                    row["source_state"],
                    row["effective_state"],
                    row["path"],
                )
                for row in result
            ),
        )
    else:
        message("No MCP registrations found in this scope.")
    return 0
