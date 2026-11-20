"""Remove a named client registration."""

from __future__ import annotations

from pathlib import Path

from conda.base.context import context

from ..clients.manager import config_target
from ..registrations import registration
from .output import message, structured


def execute(args) -> int:
    """Preview or remove an entry without looking up its source prefix."""
    target = config_target(args.client, Path.cwd(), global_scope=args.global_scope)
    result = registration(target, args.server, force=args.force, dry_run=args.dry_run)
    if context.json:
        structured(result)
    elif isinstance(result, dict):
        if result["removed"]:
            action = "Would remove" if args.dry_run else "Removed"
            message(f"{action} {args.server} from {target.path}.")
        else:
            message(f"No registration for {args.server} in {target.path}.")
        if len(target.shared_clients) > 1 and result["changed"]:
            message("This project configuration is shared by Claude Code and Copilot.")
    return 0
