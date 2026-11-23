from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import anyio

if TYPE_CHECKING:
    from argparse import Namespace

from .capabilities import Capabilities
from .execution import CondaExecutor
from .models import Diagnostic
from .policy import SafetyPolicy
from .server import CondaMCPServer


async def serve(
    executor: CondaExecutor,
    policy: SafetyPolicy = SafetyPolicy(),
) -> None:
    """Discover this installation's CLI and serve it over standard I/O."""
    program = await executor.discover()
    try:
        _, plugins = await executor.discover_plugin_state()
    except Exception as error:  # ponytail: installed plugin metadata is untrusted
        program = replace(
            program,
            diagnostics=(
                *program.diagnostics,
                Diagnostic(path=(), reason=str(error)[:512]),
            ),
        )
        plugins = ()
    capabilities = Capabilities(
        conda_executable=str(executor.executable),
        program=program,
        plugins=plugins,
    )
    await CondaMCPServer(executor, capabilities, policy).run_stdio()


def serve_from_args(args: Namespace) -> None:
    """Run the MCP server from parsed ``serve`` arguments."""
    executor = CondaExecutor.from_environment(
        timeout_seconds=args.timeout,
        output_limit_bytes=args.output_limit_bytes,
        stdin_limit_bytes=args.stdin_limit_bytes,
    )
    policy = SafetyPolicy(
        allow_write=args.allow_write,
        allow_exec=args.allow_exec,
    )
    anyio.run(serve, executor, policy, backend="asyncio")
