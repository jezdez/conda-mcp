"""Install one built wheel into a disposable conda environment and smoke test it."""

from __future__ import annotations

import email
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HOST = Path(os.environ.get("CONDA_MCP_HOST_PYTHON", sys.executable)).resolve()


def _runtime_dependencies() -> list[str]:
    dependencies = [
        "conda>=26.10",
        "python>=3.11",
        "rich>=13",
        "tomlkit>=0.13",
    ]
    if os.name == "nt":
        dependencies.append("pywin32>=311")
    return dependencies


def main() -> None:
    """Install exactly one local wheel without fetching dependencies."""
    root = Path(__file__).resolve().parents[1]
    wheels = list((root / "dist").glob("conda_mcp-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(
            f"Expected exactly one conda-mcp wheel in dist, found {len(wheels)}."
        )
    wheel = wheels[0].resolve()
    with tempfile.TemporaryDirectory() as temporary:
        temporary_root = Path(temporary)
        prefix = temporary_root / "wheel-env"
        home = temporary_root / "home"
        home.mkdir()
        condarc = temporary_root / "condarc"
        condarc.write_text("channels: [conda-forge]\n", encoding="utf-8")
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("CONDA_", "CONDA_MCP_"))
            and key not in {"CONDARC", "PYTHONPATH"}
        }
        environment.update(
            HOME=str(home),
            USERPROFILE=str(home),
            CONDARC=str(condarc),
            CONDA_PKGS_DIRS=str(temporary_root / "packages"),
            CONDA_ENVS_PATH=str(temporary_root / "envs"),
        )
        subprocess.run(
            [
                str(HOST),
                "-I",
                "-m",
                "conda",
                "create",
                "--yes",
                "--override-channels",
                "-c",
                "conda-forge",
                "-p",
                str(prefix),
                *_runtime_dependencies(),
                "pip",
            ],
            env=environment,
            check=True,
        )
        python = prefix / ("python.exe" if os.name == "nt" else "bin/python")
        with zipfile.ZipFile(wheel) as archive:
            metadata_member = next(
                name for name in archive.namelist() if name.endswith("/METADATA")
            )
            version = email.message_from_bytes(archive.read(metadata_member))["Version"]
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-build-isolation",
                str(wheel),
            ],
            env=environment,
            check=True,
        )
        smoke = temporary_root / "smoke_plugin.py"
        shutil.copy2(root / "scripts/smoke_plugin.py", smoke)
        subprocess.run(
            [
                str(python),
                "-I",
                str(smoke),
                "--installed-prefix",
                str(prefix),
                "--expected-version",
                version,
            ],
            cwd=temporary_root,
            env=environment,
            check=True,
        )


if __name__ == "__main__":
    main()
