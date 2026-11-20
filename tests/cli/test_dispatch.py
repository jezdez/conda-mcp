from __future__ import annotations

import argparse
import json

import pytest
from conda.base.context import context

from conda_mcp.cli import run as run_command
from conda_mcp.cli.parser import configure


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


def test_status_empty_json_has_no_side_effects(cli, tmp_path):
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    result = cli("status", "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
    assert before == sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))


def test_status_respects_conda_json_setting(cli):
    result = cli("status", env={"CONDA_JSON": "true"})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


def test_status_human_output_distinguishes_empty_and_registered_entries(
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
    empty = cli("status", "--client", "cursor")
    assert empty.returncode == 0, empty.stderr
    assert "No MCP registrations" in empty.stdout
    assert cli("link", "demo", "-p", str(prefix), "--client", "cursor").returncode == 0
    result = cli("status", "--client", "cursor")
    assert result.returncode == 0, result.stderr
    assert "Server" in result.stdout and "demo" in result.stdout


def test_status_filesystem_errors_are_conda_errors(cli, tmp_path):
    (tmp_path / "project/.cursor").write_text("not a directory", encoding="utf-8")
    result = cli("status", "--client", "cursor", "--json")
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


@pytest.mark.parametrize("command", ["list", "inspect", "config", "link"])
def test_missing_environment_does_not_create_prefix(cli, tmp_path, command):
    missing = tmp_path / "not-an-environment"
    arguments = [command]
    if command != "list":
        arguments.append("example")
    if command in {"config", "link"}:
        arguments += ["--client", "codex"]
    result = cli(*arguments, "-p", str(missing), "--json")
    assert result.returncode != 0
    assert "traceback" not in json.loads(result.stdout)
    assert not missing.exists()
