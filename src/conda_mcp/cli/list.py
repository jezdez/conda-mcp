"""List installed MCP servers."""

from __future__ import annotations

from conda.base.context import context

from .main import inventory
from .output import message, structured, table


def execute(args) -> int:
    """Print the selected environment's server inventory."""
    rows = inventory(args)
    if context.json:
        structured([server.to_dict() for server in rows])
    elif not rows:
        message("No installed MCP servers.")
    else:
        table(
            ("Server", "Package", "Version", "Transport", "Description"),
            (
                (
                    server.name,
                    server.package,
                    server.version,
                    "stdio" if server.stdio else "http",
                    server.description,
                )
                for server in rows
            ),
        )
    return 0
