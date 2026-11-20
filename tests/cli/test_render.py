from __future__ import annotations

import json

import pytest
import tomlkit


@pytest.mark.parametrize("client", ["claude-code", "codex", "cursor", "copilot"])
def test_render_remains_read_only_and_reports_native_format(
    cli, tmp_path, install_package, client
):
    prefix = install_package(
        manifest={
            "schema_version": 1,
            "name": "demo",
            "description": "Remote",
            "http": {
                "url": "https://example.org",
                "header_env": {"X-API-Key": "TOKEN"},
            },
        }
    )
    result = cli("render", "demo", "-p", str(prefix), "--client", client, "--json")
    assert result.returncode == 0, result.stdout
    document = json.loads(result.stdout)
    if client == "codex":
        assert document["format"] == "toml"
        assert (
            tomlkit.parse(document["snippet"])["mcp_servers"]["demo"]["url"]
            == "https://example.org"
        )
    else:
        assert document["format"] == "json"
        assert (
            json.loads(document["snippet"])["mcpServers"]["demo"]["url"]
            == "https://example.org"
        )
    assert list((tmp_path / "project").iterdir()) == []
    plain = cli("render", "demo", "-p", str(prefix), "--client", client)
    assert plain.returncode == 0 and plain.stdout == document["snippet"]


def test_inspect_json_never_fetches_remote_endpoint(cli, install_package):
    prefix = install_package(
        manifest={
            "schema_version": 1,
            "name": "demo",
            "description": "Remote",
            "http": {"url": "https://does-not-exist.invalid/mcp"},
        }
    )
    result = cli("inspect", "demo", "-p", str(prefix), "--json")
    assert result.returncode == 0, result.stdout
    assert (
        json.loads(result.stdout)["http"]["url"] == "https://does-not-exist.invalid/mcp"
    )
    missing = cli("inspect", "missing", "-p", str(prefix), "--json")
    assert missing.returncode != 0
    assert "traceback" not in json.loads(missing.stdout)
