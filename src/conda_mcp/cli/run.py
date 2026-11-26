"""Launch an installed stdio server."""

from __future__ import annotations

import os
import sys

from conda import CondaError
from conda.base.context import context

from ..run import run
from .main import select


def execute(args, *, protocol_stdout: int | None = None) -> int:
    """Validate the selected provider and keep diagnostics off stdout."""
    own_stdout = protocol_stdout is None
    if protocol_stdout is None:
        protocol_stdout = os.dup(1)
        os.dup2(2, 1)
    try:
        if context.json:
            raise CondaError("JSON mode is unavailable for stdio launch.")
        server = select(args)
        if args.package and args.package.lower() != server.package:
            raise CondaError("The installed manifest belongs to a different package.")
        return run(server, tuple(args.arguments), protocol_stdout=protocol_stdout)
    except (CondaError, OSError, ValueError) as exc:
        print(f"MCP launch failed: {str(exc)!a}", file=sys.stderr)
        return 2
    finally:
        if own_stdout:
            os.close(protocol_stdout)
