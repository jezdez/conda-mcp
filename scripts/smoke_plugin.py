"""Check installed conda-mcp registration outside the source checkout."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from importlib.metadata import distribution
from pathlib import Path

from conda.plugins.hookspec import CondaSpecs
from conda.plugins.manager import CondaPluginManager

import conda_mcp


def main() -> None:
    """Check installed registration without loading command implementations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed-prefix", type=Path)
    parser.add_argument("--expected-version")
    args = parser.parse_args()
    if args.installed_prefix:
        assert (
            Path(conda_mcp.__file__)
            .resolve()
            .is_relative_to(args.installed_prefix.resolve())
        )
    installed = distribution("conda-mcp")
    if args.expected_version:
        assert installed.version == args.expected_version
    assert any(
        entry.group == "conda"
        and entry.name == "conda-mcp"
        and entry.value == "conda_mcp.plugin"
        for entry in installed.entry_points
    )
    manager = CondaPluginManager()
    manager.add_hookspecs(CondaSpecs)
    assert manager.load_entrypoints("conda", name="conda-mcp") == 1
    [command] = manager.get_hook_results("subcommands")
    assert command.name == "mcp"
    command.configure_parser(argparse.ArgumentParser())
    assert "conda_mcp.cli.main" not in sys.modules
    assert "conda_mcp.servers" not in sys.modules
    assert "conda_mcp.cli.output" not in sys.modules
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        home = root / "home"
        home.mkdir()
        condarc = root / "condarc"
        condarc.write_text("{}\n", encoding="utf-8")
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("CONDA_") and key not in {"CONDARC", "PYTHONPATH"}
        }
        environment.update(
            HOME=str(home),
            USERPROFILE=str(home),
            CONDARC=str(condarc),
            CONDA_NO_PLUGINS="false",
        )
        for command in ("--help", "list", "status"):
            result = subprocess.run(
                [sys.executable, "-I", "-m", "conda", "mcp", command],
                cwd=root,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
    print("Installed plugin smoke checks passed.")


if __name__ == "__main__":
    main()
