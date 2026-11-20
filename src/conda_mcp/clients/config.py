"""Shared native configuration inputs and targeted document editing."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import tomlkit

from ..files import load_json
from . import ClientAdapter, kilo

MAX_CONFIG_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class Connection:
    """Literal launch data or remote references, without conda package state."""

    name: str
    command: tuple[str, ...] | None = None
    environment: tuple[str, ...] = ()
    url: str | None = None
    bearer: str | None = None
    headers: tuple[tuple[str, str], ...] = ()

    def stdio(self) -> dict[str, object]:
        """Render common stdio fields, rejecting client interpolation in paths."""
        if not self.command or not Path(self.command[0]).is_absolute():
            raise ValueError("Launch paths must be absolute.")
        if any(
            token in value
            for value in self.command
            for token in ("${", "{env:", "{file:")
        ):
            raise ValueError("Launch path conflicts with client interpolation.")
        return {"command": self.command[0], "args": list(self.command[1:])}

    def http(self, template: str) -> dict[str, object]:
        """Render an endpoint and names-only credential interpolation."""
        if self.url is None:
            raise ValueError("Server has no declared transport.")
        entry: dict[str, object] = {"url": self.url}
        headers = {key: template.format(value) for key, value in self.headers}
        if self.bearer:
            headers["Authorization"] = "Bearer " + template.format(self.bearer)
        if headers:
            entry["headers"] = headers
        return entry


@dataclass(frozen=True)
class ConfigTarget:
    """One explicit destination, without claiming the client's effective state."""

    client: str
    path: Path
    key: str
    global_scope: bool
    adapter: ClientAdapter

    @property
    def shared_clients(self) -> list[str]:
        """Identify the two clients sharing a project .mcp.json and its receipt."""
        if not self.global_scope and self.client in {"claude-code", "copilot"}:
            return ["claude-code", "copilot"]
        return [self.client]

    def check_layers(self, name: str) -> None:
        """Check native layers only for clients requiring ambiguity detection."""
        self.adapter.check_layers(self, name)


@dataclass(frozen=True)
class ClientConfig:
    """A parsed snapshot supporting one edit without changing unrelated policy."""

    target: ConfigTarget
    raw: bytes | None
    document: dict

    @classmethod
    def from_bytes(cls, target: ConfigTarget, raw: bytes | None) -> ClientConfig:
        """Parse strict native syntax and validate the selected server container."""
        try:
            if raw is None:
                document = tomlkit.document() if target.path.suffix == ".toml" else {}
            else:
                document = (
                    tomlkit.parse(raw.decode("utf-8"))
                    if target.path.suffix == ".toml"
                    else load_json(raw)
                )
            if not isinstance(document, dict) or not isinstance(
                document.get(target.key, {}), dict
            ):
                raise ValueError
            config = cls(target, raw, document)
            if any(not isinstance(value, dict) for value in config.entries.values()):
                raise ValueError
            return config
        except (ValueError, TypeError, RecursionError) as error:
            raise ValueError(
                "Invalid client configuration. File left unchanged."
            ) from error

    @property
    def entries(self) -> dict:
        """Inspect literal entries, including Kilo's nested compatible layout."""
        table = self.document.get(self.target.key, {})
        return kilo.entries(table)[0] if self.target.client == "kilo" else dict(table)

    def render(self, name: str, entry: dict | None) -> bytes:
        """Serialize one edit, preserving unrelated values and TOML comments."""
        document = deepcopy(self.document)
        table = document.setdefault(self.target.key, {})
        if self.target.client == "kilo":
            _, structural = kilo.entries(table)
            if name in structural or (
                "servers" in structural and name in table["servers"]
            ):
                raise ValueError(
                    "Selected name conflicts with nested Kilo configuration."
                )
        if entry is None:
            table.pop(name, None)
        else:
            table[name] = deepcopy(entry)
        output = (
            tomlkit.dumps(document)
            if self.target.path.suffix == ".toml"
            else json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2)
            + "\n"
        ).encode("utf-8")
        if len(output) > MAX_CONFIG_BYTES:
            raise ValueError("Client configuration is too large.")
        self.from_bytes(self.target, output)
        return output
