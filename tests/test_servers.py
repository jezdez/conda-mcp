from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from conda import CondaError
from conda.common.compat import on_win
from conda.models.records import PrefixRecord
from jsonschema import Draft202012Validator

from conda_mcp.servers import EnvironmentVariable, Http, Server, Stdio, discover


def _record(relative: str) -> PrefixRecord:
    return PrefixRecord(
        name="example", version="1", build="0", build_number=0, files=[relative]
    )


@pytest.mark.parametrize(
    "manifest",
    [
        {
            "schema_version": 1.0,
            "name": "example",
            "description": "Example",
            "stdio": {"command": "example"},
        },
        {
            "schema_version": 1,
            "name": "example",
            "description": " \t",
            "stdio": {"command": "example"},
        },
        {
            "schema_version": 1,
            "name": "example",
            "description": "Example",
            "http": {"url": "https://example.org/mcp?"},
        },
        {
            "schema_version": 1,
            "name": "example",
            "description": "Example",
            "http": {"url": "https://example.org/mcp#"},
        },
    ],
    ids=["float-version", "blank-description", "empty-query", "empty-fragment"],
)
def test_manifest_rejects_invalid_version_description_and_url(
    tmp_path: Path, manifest: dict[str, object]
):
    """Reject values that are structurally close but unsafe or semantically empty."""
    relative = "share/conda-mcp/servers/example.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CondaError, match="Invalid or duplicate MCP declaration"):
        Server.from_manifest(tmp_path, _record(relative), path)


def test_schema_matches_runtime_for_versions_and_urls(tmp_path: Path):
    """Check version types and percent-encoded URL paths in both validators."""
    schema_path = (
        Path(__file__).parents[1] / "src" / "conda_mcp" / "schema" / "server-v1.json"
    )
    validator = Draft202012Validator(
        json.loads(schema_path.read_text(encoding="utf-8"))
    )
    valid = {
        "schema_version": 1,
        "name": "example",
        "description": "Example",
        "http": {"url": "https://example.org/mcp%3Fsafe"},
    }
    invalid = {
        "schema_version": True,
        "name": "example",
        "description": "Example",
        "stdio": {"command": "example"},
    }

    assert not list(validator.iter_errors(valid))
    assert list(validator.iter_errors(invalid))

    relative = "share/conda-mcp/servers/example.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(valid), encoding="utf-8")
    assert Server.from_manifest(tmp_path, _record(relative), path).http is not None


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "con"),
        ("name", "lpt9"),
        ("stdio", {"command": "CoN"}),
        ("stdio", {"command": "server.CmD"}),
        ("stdio", {"command": "server.BAT"}),
        *[
            ("http", {"url": "https://example.org/mcp", "header_env": {name: "TOKEN"}})
            for name in (
                "Host",
                "Cookie",
                "AUTHORIZATION",
                "Content-Type",
                "Proxy-Test",
                "Mcp-Session-Id",
                "bad header",
                "",
            )
        ],
    ],
)
def test_schema_and_runtime_reject_reserved_names_and_headers(tmp_path, field, value):
    manifest = {
        "schema_version": 1,
        "name": "example",
        "description": "Example",
        "stdio": {"command": "example"},
    }
    if field == "http":
        manifest.pop("stdio")
    manifest[field] = value
    schema = json.loads(
        (Path(__file__).parents[1] / "src/conda_mcp/schema/server-v1.json").read_text()
    )
    relative = "share/conda-mcp/servers/example.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest))
    with pytest.raises(CondaError):
        Server.from_manifest(tmp_path, _record(relative), path)
    assert list(Draft202012Validator(schema).iter_errors(manifest))


@pytest.mark.parametrize(
    "name",
    ["con", "PRN", "com1", "lpt9"],
)
def test_manifest_rejects_windows_reserved_names(tmp_path: Path, name: str):
    """Reject reserved basenames even on non-Windows hosts."""
    relative = f"share/conda-mcp/servers/{name}.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": name,
                "description": "Example",
                "stdio": {"command": "example"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CondaError, match="Invalid or duplicate MCP declaration"):
        Server.from_manifest(tmp_path, _record(relative), path)


@pytest.mark.parametrize(
    "manifest",
    [
        {
            "schema_version": 1,
            "name": "example",
            "description": "Example",
            "stdio": {
                "command": "example",
                "environment": [
                    {"name": "TOKEN", "required": True},
                    {"name": "token", "required": False},
                ],
            },
        },
        {
            "schema_version": 1,
            "name": "example",
            "description": "Example",
            "http": {"url": "https://example.org", "header_env": {"Cookie": "TOKEN"}},
        },
    ],
    ids=["environment-casefold", "cookie"],
)
def test_manifest_rejects_unsafe_metadata_and_references(
    tmp_path: Path, manifest: dict[str, object]
):
    """Reject ambiguous variable names and credential headers."""
    relative = "share/conda-mcp/servers/example.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CondaError, match="Invalid or duplicate MCP declaration"):
        Server.from_manifest(tmp_path, _record(relative), path)


def test_discover_ignores_unrecorded_manifest(install_package):
    """Only package-recorded manifest paths participate in discovery."""
    prefix = install_package(files={"bin/example": b"#!/bin/sh\n"})
    path = prefix / "share/conda-mcp/servers/example.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "example",
                "description": "Example",
                "stdio": {"command": "example"},
            }
        ),
        encoding="utf-8",
    )

    assert discover(prefix) == []


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org/%3Fquery",
        "https://example.org/%23fragment",
        "https://example.org/%40userinfo",
        "https://example.org:65535/mcp",
    ],
)
def test_manifest_accepts_safe_percent_encoded_endpoint_text(tmp_path: Path, url: str):
    """Allow encoded path data while rejecting actual URL authority controls."""
    relative = "share/conda-mcp/servers/example.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "example",
                "description": "Example",
                "http": {"url": url},
            }
        ),
        encoding="utf-8",
    )

    assert Server.from_manifest(tmp_path, _record(relative), path).http is not None


@pytest.mark.parametrize(
    "url",
    [
        "https://@example.org/mcp",
        "https://:password@example.org/mcp",
        "https://example.org/mcp?#fragment",
        "https://example.org/mcp?query#",
        "https://example.org/mcp\x7f",
    ],
    ids=["empty-username", "empty-password", "empty-query", "empty-fragment", "del"],
)
def test_http_rejects_authority_and_delimiter_edge_cases(url: str):
    """Reject URL syntax that urlsplit normalizes into empty components."""
    with pytest.raises(ValueError):
        Http.from_dict({"url": url})


def test_transport_models_own_validated_manifest_parsing():
    """Parse transport and environment declarations through their frozen models."""
    assert Stdio.from_dict(
        {
            "command": "example",
            "args": ["--stdio"],
            "environment": [{"name": "TOKEN", "required": True}],
        }
    ) == Stdio("example", ("--stdio",), (EnvironmentVariable("TOKEN", True),))
    assert Http.from_dict({"url": "https://example.org/mcp"}) == Http(
        "https://example.org/mcp", None, ()
    )


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version": 1, "schema_version": 1}',
        b'{"schema_version": NaN}',
        b"\xff",
    ],
    ids=["duplicate-key", "nonfinite", "invalid-utf8"],
)
def test_manifest_rejects_invalid_json_encodings(tmp_path: Path, raw: bytes):
    """Reject malformed JSON before a partial declaration can be used."""
    relative = "share/conda-mcp/servers/example.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)

    with pytest.raises(CondaError, match="Invalid or duplicate MCP declaration"):
        Server.from_manifest(tmp_path, _record(relative), path)


@pytest.mark.parametrize(
    "transport",
    [
        {"stdio": {}},
        {"http": {"url": "http://example.com"}},
        {"stdio": {"command": "example", "args": [1]}},
    ],
)
def test_invalid_transport_is_rejected(tmp_path, transport):
    relative = "share/conda-mcp/servers/example.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "example",
                "description": "Example",
                **transport,
            }
        ),
        encoding="utf-8",
    )
    record = PrefixRecord(
        name="example", version="1", build="0", build_number=0, files=[relative]
    )
    with pytest.raises(CondaError, match="Invalid or duplicate MCP declaration"):
        Server.from_manifest(tmp_path, record, path)


def test_manifest_creates_frozen_stdio_server_with_stable_export(tmp_path: Path):
    relative = "share/conda-mcp/servers/example.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "example",
                "description": "Example server",
                "registry_name": "example-registry",
                "stdio": {
                    "command": "example-server",
                    "args": ["--stdio"],
                    "environment": [{"name": "TOKEN", "required": True}],
                },
            }
        ),
        encoding="utf-8",
    )
    record = PrefixRecord(
        name="example-package",
        version="1.2",
        build="build_0",
        build_number=0,
        files=[relative],
    )

    server = Server.from_manifest(tmp_path, record, path)

    assert server == Server(
        name="example",
        description="Example server",
        prefix=tmp_path.resolve(),
        manifest=path,
        manifest_digest=server.manifest_digest,
        package="example-package",
        version="1.2",
        build="build_0",
        channel="<unknown>",
        stdio=Stdio(
            "example-server", ("--stdio",), (EnvironmentVariable("TOKEN", True),)
        ),
        http=None,
        registry_name="example-registry",
    )
    assert server.to_dict()["manifest"] == relative
    assert server.to_dict()["prefix"] == str(tmp_path.resolve())
    with pytest.raises(FrozenInstanceError):
        setattr(server, "name", "changed")


def test_manifest_creates_http_server(tmp_path: Path):
    relative = "share/conda-mcp/servers/remote.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "remote",
                "description": "Remote server",
                "http": {
                    "url": "https://example.org:8443/mcp",
                    "bearer_token_env": "TOKEN",
                    "header_env": {"X-Request-Id": "REQUEST_ID"},
                },
            }
        ),
        encoding="utf-8",
    )
    record = PrefixRecord(
        name="remote-package", version="2", build="0", build_number=0, files=[relative]
    )

    server = Server.from_manifest(tmp_path, record, path)

    assert server.http == Http(
        "https://example.org:8443/mcp", "TOKEN", (("X-Request-Id", "REQUEST_ID"),)
    )
    assert server.stdio is None


@pytest.mark.parametrize(
    "manifest",
    [
        {
            "schema_version": True,
            "name": "example",
            "description": "x",
            "stdio": {"command": "x"},
        },
        {
            "schema_version": 1,
            "name": "example",
            "description": "x",
            "stdio": {"command": "."},
        },
        {
            "schema_version": 1,
            "name": "example",
            "description": "x",
            "http": {"url": "https://example.org/?x=1"},
        },
        {
            "schema_version": 1,
            "name": "example",
            "description": "x",
            "http": {"url": "https://example.org", "header_env": {"Host": "X"}},
        },
    ],
)
def test_manifest_rejects_unsafe_values(tmp_path: Path, manifest: dict[str, object]):
    relative = "share/conda-mcp/servers/example.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    record = PrefixRecord(
        name="example", version="1", build="0", build_number=0, files=[relative]
    )

    with pytest.raises(CondaError, match="Invalid or duplicate MCP declaration"):
        Server.from_manifest(tmp_path, record, path)


def test_discover_uses_installed_records_and_revalidates_manifest(
    install_package, tmp_path: Path
):
    relative = "share/conda-mcp/servers/example.json"
    raw = json.dumps(
        {
            "schema_version": 1,
            "name": "example",
            "description": "Example",
            "stdio": {"command": "example"},
        }
    ).encode()
    prefix = install_package(
        "example-package", files={relative: raw, "bin/example": b"#!/bin/sh\n"}
    )
    executable = prefix / "bin/example"
    executable.chmod(0o755)

    [server] = discover(prefix)

    assert server.package == "example-package"
    assert server.resolve_executable() == executable
    assert server.revalidate() == server
    (prefix / relative).write_bytes(raw.replace(b"Example", b"Changed"))
    with pytest.raises(CondaError, match="changed"):
        server.revalidate()


def test_revalidate_reloads_replaced_manifest_owner(install_package, tmp_path: Path):
    manifest = {
        "schema_version": 1,
        "name": "example",
        "description": "Example",
        "stdio": {"command": "example"},
    }
    prefix = install_package("original", manifest=manifest)
    [server] = discover(prefix)

    (tmp_path / "conda-meta" / "original-1-0.json").unlink()
    install_package("replacement", manifest=manifest)

    with pytest.raises(CondaError, match="changed"):
        server.revalidate()


def test_revalidate_ignores_unrelated_invalid_declaration(install_package):
    manifest = {
        "schema_version": 1,
        "name": "demo",
        "description": "Valid server",
        "http": {"url": "https://example.org/mcp"},
    }
    prefix = install_package(manifest=manifest)
    [server] = discover(prefix)
    install_package(
        "other", manifest={**manifest, "name": "broken", "schema_version": 999}
    )
    assert server.revalidate() == server


def test_runtime_rejects_null_credential_reference(install_package):
    prefix = install_package(
        manifest={
            "schema_version": 1,
            "name": "demo",
            "description": "Invalid credentials",
            "http": {"url": "https://example.org/mcp", "bearer_token_env": None},
        }
    )
    with pytest.raises(CondaError, match="Invalid or duplicate MCP declaration"):
        discover(prefix)


@pytest.mark.parametrize(
    "transport",
    [
        {"stdio": {"command": "probe\n"}},
        {
            "stdio": {
                "command": "probe",
                "environment": [{"name": "TOKEN\n", "required": True}],
            }
        },
        {"http": {"url": "https://example.org/mcp", "bearer_token_env": "TOKEN\n"}},
        {
            "http": {
                "url": "https://example.org/mcp",
                "header_env": {"X-Token\n": "TOKEN"},
            }
        },
        {
            "http": {
                "url": "https://example.org/mcp",
                "header_env": {"X-Token": "TOKEN\n"},
            }
        },
    ],
)
def test_manifest_rejects_trailing_newlines_in_identifiers(install_package, transport):
    prefix = install_package(
        manifest={
            "schema_version": 1,
            "name": "demo",
            "description": "Invalid identifier",
            **transport,
        }
    )
    with pytest.raises(CondaError, match="Invalid or duplicate MCP declaration"):
        discover(prefix)


def test_revalidate_rejects_replaced_manifest_channel(install_package, tmp_path: Path):
    """Treat a package channel change as a replacement during revalidation."""
    manifest = {
        "schema_version": 1,
        "name": "example",
        "description": "Example",
        "stdio": {"command": "example"},
    }
    prefix = install_package("provider", manifest=manifest)
    [server] = discover(prefix)
    record = tmp_path / "conda-meta" / "provider-1-0.json"
    content = json.loads(record.read_text(encoding="utf-8"))
    content["channel"] = "replacement"
    record.write_text(json.dumps(content), encoding="utf-8")

    with pytest.raises(CondaError, match="changed"):
        server.revalidate()


def test_executable_resolution_uses_native_directory_before_other_platform_path(
    install_package, tmp_path: Path
):
    manifest = {
        "schema_version": 1,
        "name": "example",
        "description": "Example",
        "stdio": {"command": "example"},
    }
    prefix = install_package(
        manifest=manifest,
        files={"bin/example": b"#!/bin/sh\n", "Scripts/example.exe": b"windows"},
    )
    (prefix / "bin/example").chmod(0o755)

    [server] = discover(prefix)

    expected = prefix / ("Scripts/example.exe" if on_win else "bin/example")
    assert server.resolve_executable() == expected


def test_executable_resolution_rejects_duplicate_selected_path_owners(
    install_package, tmp_path: Path
):
    manifest = {
        "schema_version": 1,
        "name": "example",
        "description": "Example",
        "stdio": {"command": "example"},
    }
    prefix = install_package(manifest=manifest, files={"bin/example": b"#!/bin/sh\n"})
    install_package("other", files={"bin/example": b"#!/bin/sh\n"})
    (prefix / "bin/example").chmod(0o755)

    [server] = discover(prefix)

    with pytest.raises(CondaError, match="ambiguously"):
        server.resolve_executable()


def test_executable_resolution_accepts_dependency_owned_symlink_target(
    install_package, tmp_path: Path
):
    manifest = {
        "schema_version": 1,
        "name": "example",
        "description": "Example",
        "stdio": {"command": "example"},
    }
    prefix = install_package(manifest=manifest, files={"bin/example": b""})
    target = prefix / "libexec/example"
    target.parent.mkdir()
    target.write_bytes(b"#!/bin/sh\n")
    target.chmod(0o755)
    (prefix / "bin/example").unlink()
    (prefix / "bin/example").symlink_to(target)
    install_package("dependency", files={"libexec/example": target.read_bytes()})
    target.chmod(0o755)

    [server] = discover(prefix)

    assert server.resolve_executable() == prefix / "bin/example"
