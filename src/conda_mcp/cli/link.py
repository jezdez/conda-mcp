"""Register an installed server in a client configuration."""

from __future__ import annotations

import json
from pathlib import Path

from conda.base.context import context

from ..clients.manager import config_target, render_entry
from ..registrations import registration
from .main import select
from .output import message, structured


def execute(args) -> int:
    """Preview or apply an entry with its package provenance."""
    target = config_target(args.client, Path.cwd(), global_scope=args.global_scope)
    server = select(args).revalidate()
    if server.stdio:
        server.resolve_executable()
    document = server.to_dict()
    entry = render_entry(server, target)
    source = {
        key: document[key]
        for key in (
            "prefix",
            "package",
            "manifest",
            "manifest_digest",
            "version",
            "build",
            "channel",
        )
    }
    result = registration(
        target, args.server, entry=entry, source=source, dry_run=args.dry_run
    )
    if context.json:
        structured(result)
    else:
        action = "Would register" if args.dry_run else "Registered"
        message(f"{action} {server.name} in {target.path}.")
        if len(target.shared_clients) > 1:
            message("This project configuration is shared by Claude Code and Copilot.")
        if args.dry_run:
            message(json.dumps(entry, ensure_ascii=True))
    return 0
