from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def cli(tmp_path: Path):
    """Run the installed plugin with isolated home and conda configuration."""
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    condarc = tmp_path / "condarc"
    condarc.write_text("{}\n", encoding="utf-8")
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("CONDA_", "KILO_"))
        and key not in {"PYTHONPATH", "CONDARC", "CODEX_HOME", "COPILOT_HOME"}
    }
    environment.update(
        HOME=str(home),
        USERPROFILE=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        APPDATA=str(home / "AppData/Roaming"),
        CONDARC=str(condarc),
        CONDA_JSON="false",
        CONDA_OFFLINE="true",
        CONDA_REPORT_ERRORS="false",
        CONDA_NO_PLUGINS="false",
        PYTHONIOENCODING="utf-8",
        NO_COLOR="1",
    )

    def run(*arguments: str, cwd: Path = project, env: dict[str, str] | None = None):
        return subprocess.run(
            [sys.executable, "-m", "conda", "mcp", *arguments],
            cwd=cwd,
            env=environment | (env or {}),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

    return run
