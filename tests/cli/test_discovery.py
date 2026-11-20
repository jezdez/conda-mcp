from __future__ import annotations

import json
import stat


def test_installed_list_reports_package_and_transport(cli, install_package):
    prefix = install_package(
        manifest={
            "schema_version": 1,
            "name": "probe",
            "description": "[red]literal\x1b[0m",
            "http": {"url": "https://example.invalid/mcp"},
        }
    )
    result = cli("list", "-p", str(prefix), "--json")
    assert result.returncode == 0, result.stderr
    [server] = json.loads(result.stdout)
    assert server["name"] == "probe"
    assert server["package"] == "provider"
    assert server["http"]["url"] == "https://example.invalid/mcp"
    human = cli("list", "-p", str(prefix))
    assert human.returncode == 0, human.stderr
    assert "Package" in human.stdout and "Transport" in human.stdout
    assert "[red]literal\\x1b[0m" in human.stdout
    assert "\x1b" not in human.stdout


def test_inspect_has_full_launch_metadata_without_execution(cli, install_package):
    prefix = install_package(
        manifest={
            "schema_version": 1,
            "name": "probe",
            "description": "Endpoint inspection",
            "http": {
                "url": "https://example.invalid/mcp",
                "bearer_token_env": "MCP_TOKEN",
            },
        }
    )
    result = cli("inspect", "probe", "-p", str(prefix))
    assert result.returncode == 0, result.stderr
    assert "https://example.invalid/mcp" in result.stdout
    assert "MCP_TOKEN" in result.stdout
    assert "provider" in result.stdout
    assert "Manifest" in result.stdout and "Channel" in result.stdout


def test_inspect_stdio_reports_full_launch_metadata_without_execution(
    cli, install_package
):
    prefix = install_package(
        manifest={
            "schema_version": 1,
            "name": "probe",
            "description": "Local inspection",
            "stdio": {
                "command": "probe",
                "args": ["--serve"],
                "environment": [{"name": "TOKEN", "required": True}],
            },
        },
        files={"bin/probe": b"#!/bin/sh\nexit 1\n"},
    )
    (prefix / "bin/probe").chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    result = cli("inspect", "probe", "-p", str(prefix))
    assert result.returncode == 0, result.stderr
    assert "Executable" in result.stdout and "probe" in result.stdout
    assert "Arguments" in result.stdout and "--serve" in result.stdout
    assert "Required environment" in result.stdout and "TOKEN" in result.stdout
    assert "Runs package activation scripts" in result.stdout


def test_render_rejects_missing_recorded_executable(cli, install_package, tmp_path):
    prefix = install_package(
        manifest={
            "schema_version": 1,
            "name": "probe",
            "description": "Missing executable",
            "stdio": {"command": "not-installed"},
        }
    )
    result = cli("render", "probe", "-p", str(prefix), "--client", "codex", "--json")
    assert result.returncode != 0
    assert "traceback" not in json.loads(result.stdout)
    assert not (tmp_path / "project/.codex").exists()
