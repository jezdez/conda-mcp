from __future__ import annotations

import argparse
import json

import pytest
from conda.base.context import context
from conda.core.prefix_data import PrefixData

from conda_mcp.cli import register as register_command
from conda_mcp.cli import render as render_command
from conda_mcp.cli import run as run_command
from conda_mcp.cli.parser import configure
from conda_mcp.clients.manager import config_target


def test_run_preserves_a_literal_child_separator(monkeypatch):
    parser = argparse.ArgumentParser()
    configure(parser)
    args = parser.parse_args(["run", "demo", "--", "--", "--version", ""])
    server = object()
    launches = []

    def launch(selected, arguments):
        launches.append((selected, arguments))
        return 17

    monkeypatch.setattr(context, "json", False)
    monkeypatch.setattr(run_command, "select", lambda args: server)
    monkeypatch.setattr(run_command, "run", launch)

    assert run_command.execute(args) == 17
    assert launches == [(server, ("--", "--version", ""))]


@pytest.mark.parametrize(
    ("command", "handler", "expected_loads"),
    [
        ("render", render_command, 2),
        ("register", register_command, 5),
    ],
)
def test_render_and_register_avoid_redundant_manifest_reloads(
    monkeypatch, tmp_path, install_package, command, handler, expected_loads
):
    prefix = install_package(
        manifest={
            "schema_version": 1,
            "name": "demo",
            "description": "Local demonstration",
            "stdio": {"command": "demo"},
        },
        files={"bin/demo": b"#!/bin/sh\nexit 0\n"},
    )
    (prefix / "bin/demo").chmod(0o755)
    parser = argparse.ArgumentParser()
    configure(parser)
    args = parser.parse_args([command, "demo", "-p", str(prefix), "--client", "codex"])
    target = config_target("codex", tmp_path / "project", global_scope=False)
    loads = 0
    original_reload = PrefixData.reload

    def reload(data):
        nonlocal loads
        loads += 1
        return original_reload(data)

    monkeypatch.setattr(context, "json", False)
    monkeypatch.setattr(handler, "config_target", lambda *args, **kwargs: target)
    monkeypatch.setattr(PrefixData, "reload", reload)

    assert handler.execute(args) == 0
    assert loads == expected_loads


def test_registry_empty_json_has_no_side_effects(cli, tmp_path):
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    result = cli("registry", "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
    assert before == sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))


def test_registry_respects_conda_json_setting(cli):
    result = cli("registry", env={"CONDA_JSON": "true"})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


def test_registry_human_output_distinguishes_empty_and_registered_entries(
    cli, install_package
):
    prefix = install_package(
        manifest={
            "schema_version": 1,
            "name": "demo",
            "description": "Remote",
            "http": {"url": "https://example.org/mcp"},
        }
    )
    empty = cli("registry", "--client", "cursor")
    assert empty.returncode == 0, empty.stderr
    assert "No MCP registrations" in empty.stdout
    assert (
        cli("register", "demo", "-p", str(prefix), "--client", "cursor").returncode == 0
    )
    result = cli("registry", "--client", "cursor")
    assert result.returncode == 0, result.stderr
    assert "Server" in result.stdout and "demo" in result.stdout
    assert "Effective" not in result.stdout


def test_registry_filesystem_errors_are_conda_errors(cli, tmp_path):
    (tmp_path / "project/.cursor").write_text("not a directory", encoding="utf-8")
    result = cli("registry", "--client", "cursor", "--json")
    assert result.returncode != 0
    document = json.loads(result.stdout)
    assert "traceback" not in document
    assert document["exception_name"] in {"CondaError", "CondaValueError"}


def test_list_uses_named_environment_from_explicit_conda_envs_path(
    cli, install_package, tmp_path
):
    prefix = install_package(
        manifest={
            "schema_version": 1,
            "name": "named",
            "description": "Named environment",
            "http": {"url": "https://example.org/mcp"},
        },
    )
    result = cli(
        "list",
        "-n",
        prefix.name,
        "--json",
        env={"CONDA_ENVS_PATH": str(tmp_path.parent)},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)[0]["prefix"] == str(prefix.resolve())


def test_list_uses_active_prefix_by_default(cli, install_package):
    prefix = install_package(
        manifest={
            "schema_version": 1,
            "name": "active",
            "description": "Active environment",
            "http": {"url": "https://example.org/mcp"},
        }
    )
    result = cli("list", "--json", env={"CONDA_PREFIX": str(prefix)})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)[0]["name"] == "active"


@pytest.mark.parametrize("command", ["list", "inspect", "render", "register"])
def test_missing_environment_does_not_create_prefix(cli, tmp_path, command):
    missing = tmp_path / "not-an-environment"
    arguments = [command]
    if command != "list":
        arguments.append("example")
    if command in {"render", "register"}:
        arguments += ["--client", "codex"]
    result = cli(*arguments, "-p", str(missing), "--json")
    assert result.returncode != 0
    assert "traceback" not in json.loads(result.stdout)
    assert not missing.exists()
