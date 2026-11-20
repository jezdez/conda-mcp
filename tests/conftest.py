"""Shared helpers that create small real conda prefix records."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


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
