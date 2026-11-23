"""Check the pywin32 guard for Windows process containment."""

from __future__ import annotations

import pytest

from conda_mcp.serving import windows


def test_missing_pywin32_reports_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_name: str) -> object:
        raise ImportError("no pywin32")

    monkeypatch.setattr(windows.importlib, "import_module", missing)

    with pytest.raises(OSError, match="pywin32 is required"):
        windows.WindowsJob()
