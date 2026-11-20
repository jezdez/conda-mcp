"""Register the MCP manager without loading command implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from conda.plugins import hookimpl

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace
    from collections.abc import Iterator

    from conda.plugins.types import CondaSubcommand


def configure_parser(parser: ArgumentParser) -> None:
    """Attach the lightweight manager parser."""
    from .cli.parser import configure

    configure(parser)


def action(args: Namespace) -> int:
    """Dispatch an explicitly selected MCP command."""
    from .cli.main import execute

    return execute(args)


@hookimpl
def conda_subcommands() -> Iterator[CondaSubcommand]:
    """Expose only the manager command."""
    from conda.plugins.types import CondaSubcommand

    yield CondaSubcommand(
        name="mcp",
        summary="Manage conda-packaged MCP servers.",
        action=action,
        configure_parser=configure_parser,
    )
