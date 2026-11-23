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
    commands = parser.add_subparsers(dest="mcp_command")
    serve = commands.add_parser(
        "serve", help="Expose a conda installation through MCP over stdio."
    )
    serve.add_argument(
        "--timeout", type=float, default=900, help="Command timeout in seconds."
    )
    serve.add_argument(
        "--output-limit-bytes", type=int, default=1_048_576, help="Retained output."
    )
    serve.add_argument(
        "--stdin-limit-bytes", type=int, default=1_048_576, help="Accepted input."
    )
    serve.add_argument(
        "--allow-write", action="store_true", help="Allow mutating conda operations."
    )
    serve.add_argument(
        "--allow-exec", action="store_true", help="Expose raw argv execution."
    )
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
        "render": "Render a native client snippet without changing any files.",
        "register": "Register a server in this directory, or globally with --global.",
        "unregister": "Remove a registration, preserving packages and other entries.",
        "registry": "List local client registrations without launching servers.",
    }
    for name, description in descriptions.items():
        command = commands.add_parser(name, help=description, description=description)
        add_parser_json(command)
        if name != "registry":
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
        if name in {"render", "register"}:
            add_parser_prefix(command)
        if name in {"register", "unregister"}:
            command.add_argument(
                "--dry-run", action="store_true", help="Preview without writing files."
            )
        if name == "unregister":
            command.add_argument(
                "--force",
                action="store_true",
                help=(
                    "Remove only the selected edited or unmanaged entry; "
                    "never bypass unsafe paths or parsing errors."
                ),
            )
