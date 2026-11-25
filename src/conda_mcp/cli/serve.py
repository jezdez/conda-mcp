"""Serve a configured conda installation over MCP."""

from __future__ import annotations

from typing import TYPE_CHECKING

from conda.exceptions import CondaValueError

if TYPE_CHECKING:
    from argparse import Namespace


def execute(args: Namespace) -> int:
    """Run the MCP server in this process, owning stdio from here on."""
    from ..serving.cli import serve_from_args

    try:
        serve_from_args(args)
    except FileNotFoundError:
        raise CondaValueError(
            "could not find conda in the launching Python environment"
        ) from None
    except ValueError as error:
        raise CondaValueError(str(error)) from error
    return 0
