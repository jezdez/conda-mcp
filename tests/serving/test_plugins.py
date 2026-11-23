from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from conda_mcp.serving.execution import CondaExecutor

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def conda_with_fixture_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[CondaExecutor, Path]]:
    try:
        executor = CondaExecutor.from_environment(timeout_seconds=30)
    except FileNotFoundError:
        pytest.skip("conda is not installed")

    plugin_root = tmp_path / "plugin"
    plugin_root.mkdir()
    (plugin_root / "conda_cli_mcp_fixture_plugin.py").write_text(
        """\
from pathlib import Path
import os

from conda import plugins


def configure_fixture_parser(parser):
    parser.add_argument("--message", required=True)


def run_configured(args):
    print(f"configured:{args.message}")
    return 0


def run_greedy(argv):
    print("greedy:" + "|".join(argv))
    return 0


def record_pre_command(command):
    event_path = Path(os.environ["CONDA_CLI_MCP_PLUGIN_EVENTS"])
    with event_path.open("a", encoding="utf-8") as stream:
        stream.write(f"pre:{command}\\n")


@plugins.hookimpl
def conda_subcommands():
    yield plugins.types.CondaSubcommand(
        name="mcp-configured-fixture",
        summary="Configured fixture command",
        action=run_configured,
        configure_parser=configure_fixture_parser,
    )
    yield plugins.types.CondaSubcommand(
        name="mcp-greedy-fixture",
        summary="Greedy fixture command",
        action=run_greedy,
    )


@plugins.hookimpl
def conda_pre_commands():
    yield plugins.types.CondaPreCommand(
        name="mcp-sentinel",
        action=record_pre_command,
        run_for={"info"},
    )
"""
    )
    dist_info = plugin_root / "conda_cli_mcp_fixture_plugin-1.2.3.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        """\
Metadata-Version: 2.1
Name: conda-cli-mcp-fixture-plugin
Version: 1.2.3
"""
    )
    (dist_info / "entry_points.txt").write_text(
        """\
[conda]
mcp-fixture = conda_cli_mcp_fixture_plugin
"""
    )

    events = tmp_path / "plugin-events.txt"
    existing_python_path = os.environ.get("PYTHONPATH")
    python_path = (
        os.pathsep.join((str(plugin_root), existing_python_path))
        if existing_python_path
        else str(plugin_root)
    )
    monkeypatch.setenv("PYTHONPATH", python_path)
    monkeypatch.setenv("CONDA_CLI_MCP_PLUGIN_EVENTS", str(events))
    monkeypatch.delenv("CONDA_NO_PLUGINS", raising=False)
    yield executor, events


@pytest.mark.anyio
async def test_normal_conda_execution_runs_non_command_hook(
    conda_with_fixture_plugin: tuple[CondaExecutor, Path],
) -> None:
    executor, events = conda_with_fixture_plugin

    disabled = await executor.execute(("--no-plugins", "info", "--json"))
    unavailable = await executor.execute(
        (
            "--no-plugins",
            "mcp-configured-fixture",
            "--message",
            "ignored",
        )
    )
    result = await executor.execute(("info", "--json"))

    assert disabled.exit_code == 0
    assert unavailable.exit_code != 0
    assert result.exit_code == 0
    assert isinstance(result.parsed_json, dict)
    assert events.read_text().splitlines() == ["pre:info"]
