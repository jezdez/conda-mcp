"""Read validated MCP declarations owned by installed conda packages."""

from __future__ import annotations

import hashlib
import re
import stat
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit

from conda import CondaError
from conda.activate import PosixActivator
from conda.common.compat import on_win
from conda.core.prefix_data import PrefixData
from conda.models.records import PrefixRecord
from jsonschema import Draft202012Validator

from .files import load_json, read_bytes

if TYPE_CHECKING:
    from typing import Any

_PATH = re.compile(r"share/conda-mcp/servers/([a-z0-9][a-z0-9_-]{0,63})\.json")
_SCHEMA = cast(
    "dict[str, Any]",
    load_json(files("conda_mcp").joinpath("schema/server-v1.json").read_bytes()),
)
_MANIFEST = Draft202012Validator(_SCHEMA)
_STDIO = _MANIFEST.evolve(schema=_SCHEMA["properties"]["stdio"])
_HTTP = _MANIFEST.evolve(schema=_SCHEMA["properties"]["http"])
_ENVIRONMENT = _MANIFEST.evolve(
    schema=_SCHEMA["properties"]["stdio"]["properties"]["environment"]["items"]
)


@dataclass(frozen=True)
class EnvironmentVariable:
    """One declared environment variable name and requirement flag."""

    name: str
    required: bool

    @classmethod
    def from_dict(cls, value: object) -> EnvironmentVariable:
        """Create a declaration from one exact manifest object."""
        if not isinstance(value, dict) or not _ENVIRONMENT.is_valid(value):
            raise ValueError("invalid environment declaration")
        return cls(**value)


@dataclass(frozen=True)
class Stdio:
    """Immutable stdio executable declaration."""

    command: str
    args: tuple[str, ...]
    environment: tuple[EnvironmentVariable, ...]

    @classmethod
    def from_dict(cls, value: object) -> Stdio:
        """Create a validated stdio declaration from a manifest transport object."""
        if not isinstance(value, dict) or not _STDIO.is_valid(value):
            raise ValueError("invalid stdio declaration")
        variables = tuple(
            EnvironmentVariable.from_dict(item) for item in value.get("environment", [])
        )
        if len({item.name.casefold() for item in variables}) != len(variables):
            raise ValueError("invalid environment declaration")
        return cls(value["command"], tuple(value.get("args", [])), variables)


@dataclass(frozen=True)
class Http:
    """Immutable HTTPS endpoint declaration with environment-only credentials."""

    url: str
    bearer_token_env: str | None
    header_env: tuple[tuple[str, str], ...]

    @classmethod
    def from_dict(cls, value: object) -> Http:
        """Create a validated HTTPS declaration from a manifest transport object."""
        if not isinstance(value, dict) or not _HTTP.is_valid(value):
            raise ValueError("invalid endpoint")
        url = value["url"]
        if any(ord(char) <= 32 or ord(char) == 127 for char in url):
            raise ValueError("invalid endpoint")
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("invalid endpoint port") from exc
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or port == 0
        ):
            raise ValueError("invalid endpoint")
        pairs = tuple(value.get("header_env", {}).items())
        if len({header.lower() for header, _ in pairs}) != len(pairs):
            raise ValueError("invalid header reference")
        return cls(url, value.get("bearer_token_env"), pairs)


@dataclass(frozen=True)
class Server:
    """One validated manifest together with its owning installed package record."""

    name: str
    description: str
    prefix: Path
    manifest: Path
    manifest_digest: str
    package: str
    version: str
    build: str
    channel: str
    stdio: Stdio | None
    http: Http | None
    registry_name: str | None

    @classmethod
    def from_manifest(cls, prefix: Path, record: PrefixRecord, path: Path) -> Server:
        """Read and validate one manifest recorded by record, or raise CondaError."""
        prefix = prefix.resolve()
        try:
            relative = path.relative_to(prefix).as_posix()
            match = _PATH.fullmatch(relative)
            if match is None or relative not in record.files:
                raise ValueError("unrecorded manifest")
            raw = read_bytes(path)
            assert raw is not None
            document = load_json(raw)
            if (
                not _MANIFEST.is_valid(document)
                or type(document.get("schema_version")) is not int
                or document["name"] != match.group(1)
            ):
                raise ValueError("invalid manifest")
            document = cast("dict[str, Any]", document)
            stdio = Stdio.from_dict(document["stdio"]) if "stdio" in document else None
            http = Http.from_dict(document["http"]) if "http" in document else None
            return cls(
                document["name"],
                document["description"],
                prefix,
                path,
                hashlib.sha256(raw).hexdigest(),
                record.name,
                record.version,
                record.build,
                str(record.channel or ""),
                stdio,
                http,
                document.get("registry_name"),
            )
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            raise CondaError(
                f"Invalid or duplicate MCP declaration: {path.stem}"
            ) from exc

    def to_dict(self) -> dict[str, object]:
        """Return a stable export representation without mutable transport data."""
        result: dict[str, object] = {
            "name": self.name,
            "description": self.description,
            "prefix": str(self.prefix),
            "manifest": self.manifest.relative_to(self.prefix).as_posix(),
            "manifest_digest": self.manifest_digest,
            "package": self.package,
            "version": self.version,
            "build": self.build,
            "channel": self.channel,
        }
        if self.registry_name is not None:
            result["registry_name"] = self.registry_name
        if self.stdio is not None:
            result["stdio"] = {
                "command": self.stdio.command,
                "args": list(self.stdio.args),
                "environment": [
                    {"name": item.name, "required": item.required}
                    for item in self.stdio.environment
                ],
            }
        if self.http is not None:
            result["http"] = {
                "url": self.http.url,
                **(
                    {"bearer_token_env": self.http.bearer_token_env}
                    if self.http.bearer_token_env
                    else {}
                ),
                **(
                    {"header_env": dict(self.http.header_env)}
                    if self.http.header_env
                    else {}
                ),
            }
        return result

    def revalidate(self) -> Server:
        """Reload this manifest and require unchanged owner and content digest."""
        for server in discover(self.prefix, name=self.name):
            if server.name == self.name:
                if (
                    server.manifest.relative_to(server.prefix),
                    server.manifest_digest,
                    server.package,
                    server.version,
                    server.build,
                    server.channel,
                ) == (
                    self.manifest.relative_to(self.prefix),
                    self.manifest_digest,
                    self.package,
                    self.version,
                    self.build,
                    self.channel,
                ):
                    return server
                break
        raise CondaError("MCP server changed during the operation.")

    def resolve_executable(self) -> Path:
        """Resolve the uniquely recorded safe stdio executable without ambient PATH."""
        if self.stdio is None:
            raise CondaError("HTTP servers have no executable.")
        records = list(
            PrefixData(self.prefix, interoperability=False).reload().iter_records()
        )
        directories = (
            (self.prefix / "bin",)
            if not on_win
            else tuple(
                Path(path) for path in PosixActivator()._get_path_dirs(str(self.prefix))
            )
        )
        for directory in directories:
            for suffix in ("", ".exe"):
                candidate = directory / f"{self.stdio.command}{suffix}"
                try:
                    relative = candidate.relative_to(self.prefix).as_posix()
                    owners = [record for record in records if relative in record.files]
                    resolved = candidate.resolve(strict=True)
                    target = resolved.relative_to(self.prefix).as_posix()
                    if (
                        len(owners) != 1
                        or resolved != candidate
                        and sum(target in record.files for record in records) != 1
                    ):
                        continue
                    mode = resolved.stat().st_mode
                    if stat.S_ISREG(mode) and (on_win or bool(mode & stat.S_IXUSR)):
                        return candidate
                except (OSError, ValueError):
                    continue
        raise CondaError("Server executable is missing or ambiguously owned.")


def discover(prefix: Path, *, name: str | None = None) -> list[Server]:
    """Validate recorded declarations, optionally selecting one server name."""
    prefix = prefix.resolve()
    data = PrefixData(prefix, interoperability=False)
    data.assert_environment()
    servers: dict[str, Server] = {}
    for record in data.reload().iter_records():
        for relative in record.files:
            if match := _PATH.fullmatch(relative):
                if name is not None and match.group(1) != name:
                    continue
                if match.group(1) in servers:
                    raise CondaError(
                        f"Invalid or duplicate MCP declaration: {match.group(1)}"
                    )
                servers[match.group(1)] = Server.from_manifest(
                    prefix, record, prefix / relative
                )
    return [servers[name] for name in sorted(servers)]
