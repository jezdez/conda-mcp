"""Configure MCP commands without importing their implementations."""

from __future__ import annotations

from argparse import REMAINDER
from typing import TYPE_CHECKING

from conda.cli.helpers import add_parser_json, add_parser_prefix

if TYPE_CHECKING:
    from argparse import ArgumentParser

_CLIENTS = ("claude-code", "copilot", "codex", "kilo", "claude-desktop", "cursor")


def configure(parser: ArgumentParser) -> None:
    """Keep environment selection independent of client destination scope."""
    commands = parser.add_subparsers(dest="mcp_command", required=True)
    listing = commands.add_parser(
        "list", help="List package-owned servers in the source environment."
    )
    add_parser_prefix(listing)
    add_parser_json(listing)
    inspect = commands.add_parser(
        "inspect",
        help="Inspect server metadata and launch requirements without execution.",
    )
    add_parser_prefix(inspect)
    add_parser_json(inspect)
    inspect.add_argument("server")
    run = commands.add_parser("run", help="Launch a local stdio server.")
    add_parser_prefix(run)
    run.add_argument(
        "--package", help="Require this exact manifest-owning package name."
    )
    run.add_argument("server")
    run.add_argument("arguments", nargs=REMAINDER)
    descriptions = {
        "config": "Export a native client snippet without changing any files.",
        "link": "Register a server in this directory, or globally with --global.",
        "unlink": "Remove a registration, preserving packages and other entries.",
        "status": "Inspect registrations without launching servers.",
    }
    for name, description in descriptions.items():
        command = commands.add_parser(name, help=description, description=description)
        add_parser_json(command)
        if name != "status":
            command.add_argument("server")
            command.add_argument("--client", choices=_CLIENTS, required=True)
        else:
            selection = command.add_mutually_exclusive_group()
            selection.add_argument("--client", choices=_CLIENTS)
            selection.add_argument("--all", action="store_true")
        command.add_argument(
            "--global",
            dest="global_scope",
            action="store_true",
            help="Use user configuration instead of the current directory.",
        )
        if name in {"config", "link"}:
            add_parser_prefix(command)
        if name in {"link", "unlink"}:
            command.add_argument(
                "--dry-run", action="store_true", help="Preview without writing files."
            )
        if name == "unlink":
            command.add_argument(
                "--force",
                action="store_true",
                help=(
                    "Remove only the selected edited or unmanaged entry; "
                    "never bypass unsafe paths or parsing errors."
                ),
            )
