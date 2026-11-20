"""Export native client configuration without writing files."""

from __future__ import annotations

from pathlib import Path

from conda.base.context import context

from ..clients.config import ClientConfig
from ..clients.manager import config_target, render_entry
from .main import select
from .output import structured


def execute(args) -> int:
    """Render a snippet for one installed server and client."""
    target = config_target(args.client, Path.cwd(), global_scope=args.global_scope)
    server = select(args).revalidate()
    if server.stdio:
        server.resolve_executable()
    entry = render_entry(server, target)
    toml = target.path.suffix == ".toml"
    snippet = (
        ClientConfig.from_bytes(target, None).render(args.server, entry).decode("utf-8")
    )
    if context.json:
        structured(
            {
                "path": str(target.path),
                "format": "toml" if toml else "json",
                "snippet": snippet,
            }
        )
    else:
        print(snippet, end="")
    return 0
