"""Inspect an installed MCP server."""

from __future__ import annotations

import json

from conda.base.context import context

from .main import select
from .output import structured, table


def execute(args) -> int:
    """Print the selected server's declaration or summary."""
    server = select(args)
    data = server.to_dict()
    if server.stdio:
        data["executable"] = str(server.resolve_executable())
    if context.json:
        structured(data)
        return 0
    rows: list[tuple[str, object]] = [
        ("Server", server.name),
        ("Description", server.description),
        ("Package", server.package),
        ("Version / build", f"{server.version} / {server.build}"),
        ("Channel", server.channel),
        ("Prefix", server.prefix),
        ("Manifest", server.manifest),
        ("Manifest SHA256", server.manifest_digest),
    ]
    if server.stdio:
        rows.extend(
            [
                ("Executable", data["executable"]),
                ("Arguments", json.dumps(list(server.stdio.args))),
                (
                    "Required environment",
                    ", ".join(v.name for v in server.stdio.environment if v.required)
                    or "None",
                ),
                (
                    "Activation",
                    "Runs package activation scripts when explicitly launched.",
                ),
            ]
        )
    elif server.http:
        rows.extend(
            [
                ("Endpoint", server.http.url),
                (
                    "Credential references",
                    ", ".join(
                        filter(
                            None,
                            [
                                server.http.bearer_token_env,
                                *(v for _, v in server.http.header_env),
                            ],
                        )
                    )
                    or "None",
                ),
            ]
        )
    table(("Field", "Value"), rows)
    return 0
