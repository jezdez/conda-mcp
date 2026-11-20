from __future__ import annotations

import argparse
import os
import subprocess
import sys
from importlib.metadata import distribution
from pathlib import Path

import pytest
from conda.plugins.hookspec import CondaSpecs
from conda.plugins.manager import CondaPluginManager

from conda_mcp.plugin import action, conda_subcommands, configure_parser


@pytest.fixture
def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="conda mcp")
    configure_parser(parser)
    return parser


def test_registers_manager_command():
    (command,) = conda_subcommands()
    assert command.name == "mcp"
    assert not command.aliases
    assert command.action is action
    assert command.configure_parser is configure_parser


@pytest.mark.parametrize(
    "command", ["list", "inspect", "render", "register", "unregister", "registry"]
)
def test_administrative_json_flag(parser, command):
    arguments = [command]
    if command not in {"list", "registry"}:
        arguments.append("example")
    if command in {"render", "register", "unregister"}:
        arguments += ["--client", "codex"]
    args = parser.parse_args([*arguments, "--json"])
    assert args.json is True


@pytest.mark.parametrize("command", ["config", "export", "link", "unlink", "status"])
def test_legacy_administrative_commands_are_rejected(parser, command):
    with pytest.raises(SystemExit) as error:
        parser.parse_args([command])
    assert error.value.code == 2


@pytest.mark.parametrize("selector", ["-n", "--name", "-p", "--prefix"])
def test_destination_commands_reject_source_selection(parser, selector):
    with pytest.raises(SystemExit) as error:
        parser.parse_args(
            ["unregister", "example", "--client", "codex", selector, "source"]
        )
    assert error.value.code == 2


@pytest.mark.parametrize(
    "arguments, code",
    [
        ([], 2),
        (["--help"], 0),
        (["list", "-n", "x", "-p", "y"], 2),
        (["register", "example"], 2),
    ],
)
def test_standard_parser_behavior(parser, arguments, code):
    with pytest.raises(SystemExit) as error:
        parser.parse_args(arguments)
    assert error.value.code == code


def test_run_preserves_remainder(parser):
    args = parser.parse_args(
        ["run", "-p", "/prefix", "example", "--", "", "--json", "a b"]
    )
    assert args.arguments == ["", "--json", "a b"]


def test_registry_defaults_to_existing_client_targets(parser):
    args = parser.parse_args(["registry"])
    assert args.client is None


def test_installed_discovery():
    entries = [
        entry
        for entry in distribution("conda-mcp").entry_points
        if entry.group == "conda"
    ]
    assert [(entry.name, entry.value) for entry in entries] == [
        ("conda-mcp", "conda_mcp.plugin")
    ]
    manager = CondaPluginManager()
    manager.add_hookspecs(CondaSpecs)
    assert manager.load_entrypoints("conda", name="conda-mcp") == 1
    [command] = manager.get_hook_results("subcommands")
    parser = argparse.ArgumentParser()
    command.configure_parser(parser)
    assert (
        parser.parse_args(["render", "example", "--client", "codex"]).mcp_command
        == "render"
    )


def test_fresh_process_lazy_imports(tmp_path):
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        cwd=tmp_path,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


if __name__ == "__main__":
    test_installed_discovery()
    parser = argparse.ArgumentParser()
    configure_parser(parser)
    assert (
        parser.parse_args(["render", "example", "--client", "codex"]).mcp_command
        == "render"
    )
    for module in sys.modules:
        assert module not in {
            "conda_mcp.servers",
            "conda_mcp.clients",
            "conda_mcp.registrations",
            "conda_mcp.run",
            "conda_mcp.files",
        }
        assert (
            not module.startswith("conda_mcp.cli.") or module == "conda_mcp.cli.parser"
        )
