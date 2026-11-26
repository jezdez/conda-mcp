"""Shared helpers that create small real conda prefix records."""

from __future__ import annotations

import json
import os
import subprocess
import sysconfig
import venv
from pathlib import Path

import pytest


@pytest.fixture
def noisy_conda_venv(tmp_path: Path) -> Path:
    """Expose an installed conda plugin that prints during module import."""
    root = tmp_path / "venv"
    venv.EnvBuilder(system_site_packages=True, with_pip=False).create(root)
    python = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    site = Path(
        subprocess.check_output(
            [
                str(python),
                "-I",
                "-c",
                "import sysconfig; print(sysconfig.get_path('purelib'))",
            ],
            text=True,
        ).strip()
    )
    (site / "conda_mcp_noisy_plugin.py").write_text(
        """\
print("NOISY_CONDA_PLUGIN")
from conda import plugins

@plugins.hookimpl
def conda_subcommands():
    return ()
""",
        encoding="utf-8",
    )
    metadata = site / "conda_mcp_noisy_plugin-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: conda-mcp-noisy-plugin\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "entry_points.txt").write_text(
        "[conda]\nmcp-noisy = conda_mcp_noisy_plugin\n",
        encoding="utf-8",
    )
    conda = Path(sysconfig.get_path("scripts")) / (
        "conda.exe" if os.name == "nt" else "conda"
    )
    target = python.parent / conda.name
    if os.name == "nt":
        target.write_bytes(conda.read_bytes())
    else:
        target.symlink_to(conda)
    return python


@pytest.fixture
def install_package(tmp_path: Path):
    """Install declared files and one matching on-disk conda package record."""

    def install(
        name: str = "provider",
        manifest: dict[str, object] | None = None,
        files: dict[str, bytes] | None = None,
    ) -> Path:
        files = {} if files is None else dict(files)
        if manifest is not None:
            server_name = manifest.get("name", "server")
            assert isinstance(server_name, str)
            files[f"share/conda-mcp/servers/{server_name}.json"] = json.dumps(
                manifest
            ).encode()
        (tmp_path / "conda-meta").mkdir(exist_ok=True)
        (tmp_path / "conda-meta" / "history").write_text("", encoding="utf-8")
        for relative, content in files.items():
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        record = tmp_path / "conda-meta" / f"{name}-1-0.json"
        record.write_text(
            json.dumps(
                {
                    "name": name,
                    "version": "1",
                    "build": "0",
                    "build_number": 0,
                    "channel": "test",
                    "files": list(files),
                }
            ),
            encoding="utf-8",
        )
        return tmp_path

    return install
