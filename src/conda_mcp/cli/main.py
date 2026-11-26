"""Dispatch commands and select their installed server sources."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

from conda import CondaError
from conda.base.context import context, determine_target_prefix, locate_prefix_by_name
from conda.exceptions import CondaValueError

from ..servers import Server, discover

if TYPE_CHECKING:
    from argparse import Namespace


def execute(args: Namespace) -> int:
    """Load only the selected command handler."""
    if args.mcp_command is None:
        from argparse import ArgumentParser

        from .parser import configure

        helper = ArgumentParser(
            prog="conda mcp", description="Manage conda-packaged MCP servers."
        )
        configure(helper)
        print(helper.format_help(), end="")
        return 0
    try:
        return import_module(f".{args.mcp_command}", __package__).execute(args)
    except CondaError:
        raise
    except (OSError, ValueError) as error:
        if isinstance(error, OSError):
            message = error.strerror or type(error).__name__
        else:
            message = str(error)
        raise CondaValueError(message) from error


def inventory(args: Namespace, *, name: str | None = None) -> list[Server]:
    """Discover servers in one existing conda prefix."""
    prefix = (
        locate_prefix_by_name(args.name)
        if args.name
        else determine_target_prefix(context, args)
    )
    return discover(Path(prefix).resolve(), name=name)


def select(args: Namespace) -> Server:
    """Select one installed server by name."""
    for row in inventory(args, name=args.server):
        return row
    raise CondaError("No installed MCP server with that name.")
