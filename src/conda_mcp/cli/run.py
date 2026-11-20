"""Launch an installed stdio server."""

from __future__ import annotations

import sys

from conda import CondaError
from conda.base.context import context

from ..run import run
from .main import select


def execute(args) -> int:
    """Validate the selected provider and keep diagnostics off stdout."""
    try:
        if context.json:
            raise CondaError("JSON mode is unavailable for stdio launch.")
        server = select(args)
        if args.package and args.package.lower() != server.package:
            raise CondaError("The installed manifest belongs to a different package.")
        return run(server, tuple(args.arguments))
    except (CondaError, OSError, ValueError) as exc:
        print(f"MCP launch failed: {str(exc)!a}", file=sys.stderr)
        return 2
