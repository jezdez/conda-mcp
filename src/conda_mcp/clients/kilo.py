"""Kilo configuration, compatible document layouts, and inert layer inspection."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..files import load_json, read_bytes
from . import ClientAdapter

if TYPE_CHECKING:
    from .config import ConfigTarget, Connection


@dataclass(frozen=True)
class KiloAdapter(ClientAdapter):
    """Kilo destination and local or remote connection rendering."""

    key: str = "mcp"

    def destination(self, root: Path, *, global_scope: bool) -> Path:
        """Select only the native JSON write target, never rewrite JSONC layers."""
        if global_scope:
            return (
                Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
                / "kilo/kilo.json"
            )
        return root / ".kilo/kilo.json"

    def render(
        self, connection: Connection, *, global_scope: bool
    ) -> dict[str, object]:
        """Render a local argv vector or supported trusted remote references."""
        if connection.command is not None:
            connection.stdio()
            return {"type": "local", "command": list(connection.command)}
        if not global_scope and (connection.bearer or connection.headers):
            raise ValueError(
                "Kilo project configuration cannot forward remote secrets."
            )
        return {"type": "remote", **connection.http("{{env:{}}}")}

    def check_layers(self, target: ConfigTarget, name: str) -> None:
        """Refuse selected-name collisions without reading secrets or running Kilo."""
        check_layers(target, name)


def entries(table: dict) -> tuple[dict, set[str]]:
    """Inspect flat and nested layouts without transforming the original data."""
    result = dict(table)
    structural: set[str] = set()
    nested = table.get("servers")
    if isinstance(nested, dict) and nested.get("type") not in ("local", "remote"):
        structural.add("servers")
        result.pop("servers")
        if any(key in result for key in nested):
            raise ValueError("Conflicting flat and nested Kilo configuration.")
        result.update(nested)
    timeout = table.get("timeout")
    if isinstance(timeout, dict) and set(timeout) <= {
        "startup",
        "request",
        "catalog",
        "execution",
    }:
        structural.add("timeout")
        result.pop("timeout")
    if any(not isinstance(value, dict) for value in result.values()):
        raise ValueError("Invalid Kilo server configuration.")
    return result, structural


def check_layers(target: ConfigTarget, name: str) -> None:
    """Refuse selected-name collisions without reading secrets or running Kilo."""
    if any(
        os.environ.get(key)
        for key in ("KILO_CONFIG", "KILO_CONFIG_DIR", "KILO_CONFIG_CONTENT")
    ):
        raise ValueError("Unknown Kilo configuration override. Use config export.")
    if not target.global_scope and os.environ.get("KILO_DISABLE_PROJECT_CONFIG"):
        raise ValueError("Kilo project configuration is disabled. Use config export.")
    home = Path.home()
    global_dir = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "kilo"
    if not global_dir.is_absolute():
        raise ValueError("XDG_CONFIG_HOME must contain an absolute path.")
    directories = [global_dir, home / ".kilo", home / ".kilocode"]
    if not target.global_scope:
        root = target.path.parent.parent
        for parent in (root, *root.parents):
            directories.extend((parent, parent / ".kilo", parent / ".kilocode"))
            if parent == home or (parent / ".git").exists():
                break
    filenames = ("kilo.json", "kilo.jsonc", "opencode.json", "opencode.jsonc")
    candidates = {
        directory / filename for directory in directories for filename in filenames
    }
    candidates.add(global_dir / "config.json")
    for path in sorted(candidates):
        if path == target.path:
            continue
        try:
            raw = read_bytes(path, limit=16 * 1024 * 1024, missing_ok=True)
            if raw is None:
                continue
            table = load_json(raw, comments=True).get("mcp", {})
            if not isinstance(table, dict):
                raise ValueError
            defined, _ = entries(table)
        except (OSError, ValueError, RecursionError) as error:
            raise ValueError(
                "Invalid or redirected Kilo configuration layer."
            ) from error
        if name in defined:
            raise ValueError(
                "Selected name appears in another Kilo layer. Use config export."
            )
