from __future__ import annotations

import json

import pytest

from conda_mcp.clients.config import ClientConfig, ConfigTarget
from conda_mcp.clients.cursor import CursorAdapter
from conda_mcp.clients.manager import config_target


def test_json_document_edit_preserves_unrelated_values(tmp_path):
    target = config_target("cursor", tmp_path, global_scope=False)
    original = {"mcpServers": {"foreign": {"enabled": False}}, "trust": ["unchanged"]}
    config = ClientConfig.from_bytes(target, json.dumps(original).encode())
    rendered = config.render("demo", {"url": "https://example.org/mcp"})
    assert json.loads(rendered) == {
        **original,
        "mcpServers": {
            **original["mcpServers"],
            "demo": {"url": "https://example.org/mcp"},
        },
    }
    assert config.entries == original["mcpServers"]


def test_toml_edit_preserves_comments_and_disabled_servers(tmp_path):
    target = config_target("codex", tmp_path, global_scope=False)
    raw = b"# personal configuration\n[mcp_servers.foreign]\nenabled=false # preserve\n"
    config = ClientConfig.from_bytes(target, raw)
    rendered = config.render(
        "demo", {"command": "/bin/program", "args": ["", "two words"]}
    )
    assert b"# personal configuration" in rendered
    assert b"enabled=false # preserve" in rendered
    edited = ClientConfig.from_bytes(target, rendered)
    assert edited.entries["demo"]["args"] == ["", "two words"]
    assert ClientConfig.from_bytes(target, edited.render("demo", None)).entries == {
        "foreign": {"enabled": False}
    }


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b'{"mcpServers":null}',
        b'{"x":NaN}',
        b'{"x":1,"x":2}',
        b'{"mcpServers":{"demo":null}}',
        b"\xff",
    ],
)
def test_invalid_client_config_reports_no_file_content(tmp_path, raw):
    target = config_target("cursor", tmp_path, global_scope=False)
    with pytest.raises(ValueError, match="configuration"):
        ClientConfig.from_bytes(target, raw)


@pytest.mark.parametrize("raw", [b"[mcp_servers", b"\xff"])
def test_invalid_toml_client_config_reports_no_file_content(tmp_path, raw):
    target = config_target("codex", tmp_path, global_scope=False)
    with pytest.raises(ValueError, match="configuration"):
        ClientConfig.from_bytes(target, raw)


def test_config_can_render_a_new_document_without_any_filesystem_write(tmp_path):
    target = config_target("codex", tmp_path, global_scope=False)
    config = ClientConfig.from_bytes(target, None)
    assert config.entries == {}
    assert config.raw is None
    assert b"mcp_servers.demo" in config.render("demo", {"url": "https://example.org"})
    assert not target.path.parent.exists()


def test_kilo_nested_source_is_inspected_without_interpolation_or_mutation(tmp_path):
    target = config_target("kilo", tmp_path, global_scope=False)
    raw = (
        b'{"mcp":{"servers":{"nested":{"type":"remote","url":"{file:PRIVATE}"}},'
        b'"timeout":{"startup":50}}}'
    )
    config = ClientConfig.from_bytes(target, raw)
    assert set(config.entries) == {"nested"}
    with pytest.raises(ValueError, match="nested"):
        config.render("nested", {"type": "remote", "url": "https://example.org"})
    rendered = json.loads(
        config.render("demo", {"type": "remote", "url": "https://example.org"})
    )
    assert rendered["mcp"]["servers"]["nested"]["url"] == "{file:PRIVATE}"
    assert rendered["mcp"]["timeout"] == {"startup": 50}


def test_kilo_structural_names_can_also_be_literal_server_names(tmp_path):
    target = config_target("kilo", tmp_path, global_scope=False)
    entry = {"type": "remote", "url": "https://example.org"}
    config = ClientConfig.from_bytes(
        target, json.dumps({"mcp": {"servers": entry, "timeout": entry}}).encode()
    )
    assert config.entries == {"servers": entry, "timeout": entry}


def test_kilo_rejects_duplicate_flat_and_nested_server_names(tmp_path):
    target = config_target("kilo", tmp_path, global_scope=False)
    raw = json.dumps(
        {
            "mcp": {
                "demo": {"type": "remote", "url": "https://flat.example"},
                "servers": {
                    "demo": {"type": "remote", "url": "https://nested.example"}
                },
            }
        }
    ).encode()
    with pytest.raises(ValueError, match="Invalid client configuration"):
        ClientConfig.from_bytes(target, raw)


def test_kilo_timeout_settings_do_not_prevent_an_unrelated_edit(tmp_path):
    target = config_target("kilo", tmp_path, global_scope=False)
    config = ClientConfig.from_bytes(
        target,
        b'{"mcp":{"timeout":{"startup":50},"existing":{"type":"remote","url":"https://example.org"}}}',
    )
    rendered = json.loads(
        config.render("demo", {"type": "remote", "url": "https://demo.example"})
    )
    assert rendered["mcp"]["timeout"] == {"startup": 50}
    assert rendered["mcp"]["demo"]["url"] == "https://demo.example"


def test_unknown_container_is_not_inferred_from_client_json(tmp_path):
    target = ConfigTarget(
        "cursor", tmp_path / "mcp.json", "mcpServers", False, CursorAdapter()
    )
    with pytest.raises(ValueError, match="configuration"):
        ClientConfig.from_bytes(target, b'{"mcpServers":["PRIVATE"]}')
