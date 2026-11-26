from __future__ import annotations

import sys
from dataclasses import is_dataclass, replace
from inspect import isabstract

import pytest
from conda import CondaError

from conda_mcp.clients import manager as clients
from conda_mcp.clients.config import Connection
from conda_mcp.clients.manager import (
    CLIENTS,
    ClientAdapter,
    config_target,
    render_entry,
)
from conda_mcp.servers import EnvironmentVariable, Http, Server, Stdio


@pytest.fixture
def server(tmp_path):
    """Provide validated data without launching or looking up an executable."""
    return Server(
        name="demo",
        description="Example",
        prefix=tmp_path,
        manifest=tmp_path / "share/conda-mcp/servers/demo.json",
        manifest_digest="a" * 64,
        package="provider",
        version="1",
        build="0",
        channel="test",
        registry_name=None,
        http=None,
        stdio=Stdio("example", (), (EnvironmentVariable("TOKEN", True),)),
    )


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Keep every native client destination and layer inside the test directory."""
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USERPROFILE", str(path))
    for name in (
        "CODEX_HOME",
        "COPILOT_HOME",
        "XDG_CONFIG_HOME",
        "APPDATA",
        "KILO_CONFIG",
        "KILO_CONFIG_DIR",
        "KILO_CONFIG_CONTENT",
    ):
        monkeypatch.delenv(name, raising=False)
    return path


@pytest.mark.parametrize(
    "client,filename",
    [
        ("claude-code", ".mcp.json"),
        ("copilot", ".mcp.json"),
        ("codex", ".codex/config.toml"),
        ("kilo", ".kilo/kilo.json"),
        ("cursor", ".cursor/mcp.json"),
    ],
)
def test_project_targets(client, filename, tmp_path):
    assert (
        config_target(client, tmp_path, global_scope=False).path == tmp_path / filename
    )


def test_codex_http_references(tmp_path, server):
    target = config_target("codex", tmp_path, global_scope=False)
    assert render_entry(
        replace(server, stdio=None, http=Http("https://example.org/mcp", "TOKEN", ())),
        target,
    ) == {
        "url": "https://example.org/mcp",
        "bearer_token_env_var": "TOKEN",
    }


@pytest.mark.parametrize("client", clients.CLIENTS)
def test_stdio_uses_absolute_host_and_exact_manifest_owner(client, server, home):
    target = config_target(client, server.prefix, global_scope=True)
    entry = render_entry(server, target)
    args = [
        "-I",
        "-m",
        "conda_mcp._stdio",
        "run",
        "-p",
        str(server.prefix),
        "--package",
        "provider",
        "demo",
    ]
    expected = {"command": sys.executable, "args": args}
    if client == "kilo":
        expected = {"type": "local", "command": [sys.executable, *args]}
    elif client in {"claude-code", "copilot", "cursor"}:
        expected["type"] = "stdio"
    elif client == "codex":
        expected["env_vars"] = ["TOKEN"]
    assert entry == expected
    assert "env" not in entry


@pytest.mark.parametrize(
    "client,filename",
    [
        ("claude-code", ".claude.json"),
        ("copilot", ".copilot/mcp-config.json"),
        ("codex", ".codex/config.toml"),
        ("kilo", ".config/kilo/kilo.json"),
        ("cursor", ".cursor/mcp.json"),
    ],
)
def test_global_targets(client, filename, tmp_path, home):
    assert config_target(client, tmp_path, global_scope=True).path == home / filename


@pytest.mark.parametrize(
    "client,variable,filename",
    [
        ("copilot", "COPILOT_HOME", "mcp-config.json"),
        ("codex", "CODEX_HOME", "config.toml"),
        ("kilo", "XDG_CONFIG_HOME", "kilo/kilo.json"),
    ],
)
def test_native_config_home_only_applies_to_global(
    client, variable, filename, tmp_path, home, monkeypatch
):
    override = tmp_path / "custom"
    monkeypatch.setenv(variable, str(override))
    assert (
        config_target(client, tmp_path, global_scope=True).path == override / filename
    )
    assert config_target(client, tmp_path, global_scope=False).path.is_relative_to(
        tmp_path
    )
    monkeypatch.setenv(variable, "relative")
    with pytest.raises(CondaError, match="absolute"):
        config_target(client, tmp_path, global_scope=True)


@pytest.mark.parametrize(
    "platform,filename",
    [
        ("darwin", "Library/Application Support/Claude/claude_desktop_config.json"),
        ("win32", "AppData/Roaming/Claude/claude_desktop_config.json"),
        ("linux", ".config/Claude/claude_desktop_config.json"),
    ],
)
def test_desktop_native_paths(platform, filename, tmp_path, home, monkeypatch):
    monkeypatch.setattr(clients.sys, "platform", platform)
    assert (
        config_target("claude-desktop", tmp_path, global_scope=True).path
        == home / filename
    )


def test_desktop_rejects_project_and_remote(tmp_path, home, server):
    with pytest.raises(CondaError, match="global"):
        config_target("claude-desktop", tmp_path, global_scope=False)
    target = config_target("claude-desktop", tmp_path, global_scope=True)
    with pytest.raises(CondaError, match="stdio"):
        render_entry(
            replace(server, stdio=None, http=Http("https://example.org", None, ())),
            target,
        )


def test_desktop_rejects_unsupported_platform(tmp_path, home, monkeypatch):
    monkeypatch.setattr(clients.sys, "platform", "freebsd")
    with pytest.raises(CondaError, match="Unsupported Claude Desktop platform"):
        config_target("claude-desktop", tmp_path, global_scope=True)


def test_unknown_client_and_home_scope_are_explicit(tmp_path, home):
    with pytest.raises(CondaError, match="Unsupported client"):
        config_target("unknown", tmp_path, global_scope=False)
    with pytest.raises(CondaError, match="global"):
        config_target("cursor", home, global_scope=False)


@pytest.mark.parametrize(
    "client,template,type_value",
    [
        ("claude-code", "${TOKEN}", "http"),
        ("copilot", "${TOKEN}", "http"),
        ("cursor", "${env:TOKEN}", None),
        ("kilo", "{env:TOKEN}", "remote"),
    ],
)
def test_http_references_never_expand_credentials(
    client, template, type_value, server, home, monkeypatch
):
    monkeypatch.setenv("TOKEN", "secret-value-not-for-storage")
    remote = replace(
        server,
        stdio=None,
        http=Http("https://example.org/mcp", "TOKEN", (("X-Key", "TOKEN"),)),
    )
    entry = render_entry(
        remote, config_target(client, server.prefix, global_scope=True)
    )
    expected = {
        "url": "https://example.org/mcp",
        "headers": {"Authorization": f"Bearer {template}", "X-Key": template},
    }
    if type_value:
        expected["type"] = type_value
    assert entry == expected
    assert "secret-value" not in repr(entry)


def test_kilo_project_requires_inheritable_remote_configuration(server):
    target = config_target("kilo", server.prefix, global_scope=False)
    remote = replace(server, stdio=None, http=Http("https://example.org", "TOKEN", ()))
    with pytest.raises(CondaError, match="secrets"):
        render_entry(remote, target)
    assert render_entry(
        replace(remote, http=Http("https://example.org", None, ())), target
    ) == {
        "type": "remote",
        "url": "https://example.org",
    }


@pytest.mark.parametrize("component", ["${TOKEN}", "{env:TOKEN}", "{file:secret}"])
def test_client_interpolation_in_launch_paths_is_rejected(server, component):
    unsafe = replace(server, prefix=server.prefix / component)
    with pytest.raises(CondaError, match="interpolation"):
        render_entry(unsafe, config_target("cursor", server.prefix, global_scope=False))


def test_native_stdio_rejects_relative_host_executable(tmp_path):
    with pytest.raises(ValueError, match="absolute"):
        Connection("demo", command=("python", "-m", "demo")).stdio()


@pytest.mark.parametrize("client", ["codex", "cursor", "kilo"])
def test_native_clients_reject_a_server_without_transport(client, tmp_path, home):
    target = config_target(client, tmp_path, global_scope=True)
    with pytest.raises(CondaError, match="no declared transport"):
        render_entry(
            replace(
                Server(
                    name="demo",
                    description="Example",
                    prefix=tmp_path,
                    manifest=tmp_path / "server.json",
                    manifest_digest="a" * 64,
                    package="provider",
                    version="1",
                    build="0",
                    channel="test",
                    registry_name=None,
                    http=None,
                    stdio=None,
                )
            ),
            target,
        )


def test_codex_omits_empty_stdio_environment_list(server, home):
    target = config_target("codex", server.prefix, global_scope=True)
    entry = render_entry(replace(server, stdio=Stdio("example", (), ())), target)
    assert entry["command"] == sys.executable
    assert "env_vars" not in entry


def test_kilo_rejects_disabled_project_configuration(server, home, monkeypatch):
    target = config_target("kilo", server.prefix, global_scope=False)
    monkeypatch.setenv("KILO_DISABLE_PROJECT_CONFIG", "1")
    with pytest.raises(ValueError, match="disabled"):
        target.check_layers("demo")


@pytest.mark.parametrize(
    "variable", ["KILO_CONFIG", "KILO_CONFIG_DIR", "KILO_CONFIG_CONTENT"]
)
def test_kilo_rejects_unknown_configuration_overrides(
    server, home, monkeypatch, variable
):
    target = config_target("kilo", server.prefix, global_scope=False)
    monkeypatch.setenv(variable, "configured-elsewhere")
    with pytest.raises(ValueError, match="Unknown Kilo configuration override"):
        target.check_layers("demo")


@pytest.mark.parametrize("client", ["claude-code", "copilot"])
@pytest.mark.parametrize("name", ["workspace", "claude-in-chrome", "computer-use"])
def test_reserved_client_names_are_not_written(client, server, name):
    with pytest.raises(CondaError, match="reserved"):
        render_entry(
            replace(server, name=name),
            config_target(client, server.prefix, global_scope=False),
        )


@pytest.mark.parametrize("client", clients.CLIENTS)
def test_each_native_client_has_a_frozen_typed_adapter(client):
    adapter = clients.CLIENTS[client]
    assert isabstract(ClientAdapter)
    assert issubclass(type(adapter), ClientAdapter)
    assert isinstance(adapter, ClientAdapter)
    assert is_dataclass(adapter)
    assert adapter.__dataclass_params__.frozen
    assert adapter.__class__.__module__ == (
        "conda_mcp.clients." + client.replace("-", "_")
    )
    assert (
        adapter.__class__.__name__
        == "".join(part.capitalize() for part in client.split("-")) + "Adapter"
    )
    assert CLIENTS[client] is adapter


def test_adapter_base_defines_noop_layers_except_kilo(server, home, monkeypatch):
    """Kilo's project-disable setting must not affect other clients."""
    monkeypatch.setenv("KILO_DISABLE_PROJECT_CONFIG", "1")

    config_target("cursor", server.prefix, global_scope=False).check_layers("demo")

    with pytest.raises(ValueError, match="disabled"):
        config_target("kilo", server.prefix, global_scope=False).check_layers("demo")
