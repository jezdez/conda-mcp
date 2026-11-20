from __future__ import annotations

import json

import pytest


@pytest.fixture
def remote(install_package):
    return install_package(
        manifest={
            "schema_version": 1,
            "name": "demo",
            "description": "Remote demonstration",
            "http": {"url": "https://example.org/mcp", "bearer_token_env": "TOKEN"},
        }
    )


@pytest.mark.parametrize("client", ["claude-code", "copilot", "codex", "cursor"])
def test_register_registry_and_unregister_are_complete_json(
    cli, tmp_path, remote, client
):
    result = cli(
        "register",
        "demo",
        "-p",
        str(remote),
        "--client",
        client,
        "--json",
        env={"TOKEN": "never-persist-this"},
    )
    assert result.returncode == 0, result.stderr + result.stdout
    linked = json.loads(result.stdout)
    assert linked["changed"] is True
    assert "never-persist-this" not in result.stdout
    result = cli("registry", "--client", client, "--json")
    [state] = json.loads(result.stdout)
    assert state["name"] == "demo" and state["state"] == "managed"
    assert state["source_state"] == "current"
    result = cli("unregister", "demo", "--client", client, "--json")
    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["removed"] is True
    result = cli("unregister", "demo", "--client", client, "--json")
    assert json.loads(result.stdout)["removed"] is False
    assert not (tmp_path / "home" / ".claude.json").exists()


def test_human_register_confirmation_warns_both_shared_clients(cli, remote):
    result = cli("register", "demo", "-p", str(remote), "--client", "claude-code")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "Registered demo" in result.stdout
    assert "Claude Code" in result.stdout and "Copilot" in result.stdout
    assert "{'" not in result.stdout


@pytest.mark.parametrize("columns", ["40", "80"])
def test_register_dry_run_shows_destination_and_entry_without_writes(
    cli, tmp_path, remote, columns
):
    result = cli(
        "register",
        "demo",
        "-p",
        str(remote),
        "--client",
        "codex",
        "--dry-run",
        env={"COLUMNS": columns},
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "Would register demo" in result.stdout
    assert str(tmp_path / "project" / ".codex" / "config.toml") in result.stdout
    assert json.loads(result.stdout.splitlines()[-1]) == {
        "url": "https://example.org/mcp",
        "bearer_token_env_var": "TOKEN",
    }
    assert not (tmp_path / "project" / ".codex").exists()


def test_force_never_bypasses_malformed_configuration(cli, tmp_path):
    config = tmp_path / "project" / ".mcp.json"
    raw = '{"mcpServers":{"demo":null}}'
    config.write_text(raw)
    result = cli("unregister", "demo", "--client", "claude-code", "--force", "--json")
    assert result.returncode != 0
    document = json.loads(result.stdout)
    assert "traceback" not in document
    assert config.read_text() == raw


def test_unlink_after_source_removal_is_destination_only(cli, tmp_path, remote):
    assert (
        cli(
            "register", "demo", "-p", str(remote), "--client", "cursor", "--json"
        ).returncode
        == 0
    )
    (remote / "conda-meta/provider-1-0.json").unlink()
    (remote / "share/conda-mcp/servers/demo.json").unlink()
    [state] = json.loads(cli("registry", "--client", "cursor", "--json").stdout)
    assert state["source_state"] == "missing"
    result = cli("unregister", "demo", "--client", "cursor")
    assert result.returncode == 0, result.stderr
    assert "Removed demo" in result.stdout
    assert "No registration" in cli("unregister", "demo", "--client", "cursor").stdout


def test_unregister_dry_run_describes_removal_without_writing(cli, remote):
    assert (
        cli(
            "register", "demo", "-p", str(remote), "--client", "cursor", "--json"
        ).returncode
        == 0
    )
    result = cli("unregister", "demo", "--client", "cursor", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "Would remove demo" in result.stdout
    [state] = json.loads(cli("registry", "--client", "cursor", "--json").stdout)
    assert state["name"] == "demo"


def test_link_home_requires_explicit_global_even_when_cwd_is_home(
    cli, tmp_path, remote
):
    result = cli(
        "register",
        "demo",
        "-p",
        str(remote),
        "--client",
        "claude-code",
        "--json",
        cwd=tmp_path / "home",
    )
    assert result.returncode != 0
    assert "--global" in result.stdout
    assert not (tmp_path / "home" / ".mcp.json").exists()
    result = cli(
        "register",
        "demo",
        "-p",
        str(remote),
        "--client",
        "claude-code",
        "--global",
        "--json",
    )
    assert result.returncode == 0, result.stdout
    assert (tmp_path / "home" / ".claude.json").is_file()


def test_shared_receipt_reports_both_clients(cli, remote):
    assert (
        cli(
            "register", "demo", "-p", str(remote), "--client", "claude-code", "--json"
        ).returncode
        == 0
    )
    states = json.loads(cli("registry", "--all", "--json").stdout)
    assert len(states) == 1
    assert all(row["shared_clients"] == ["claude-code", "copilot"] for row in states)


def test_run_never_wraps_http_or_missing_source_errors_as_json(cli, remote):
    result = cli("run", "-p", str(remote), "demo")
    assert result.returncode != 0
    assert result.stdout == ""
    assert "stdio" in result.stderr.lower()
    result = cli("run", "-p", str(remote / "missing"), "demo")
    assert result.returncode != 0 and result.stdout == ""
    assert "traceback" not in result.stderr.lower()


def test_run_package_is_exact_owner_not_matchspec(cli, remote):
    result = cli("run", "-p", str(remote), "--package", "provider>=1", "demo")
    assert result.returncode != 0 and result.stdout == ""
    assert "package" in result.stderr.lower()
