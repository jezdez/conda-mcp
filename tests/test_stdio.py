from __future__ import annotations

import subprocess
import sys


def test_direct_launcher_rejects_administrative_commands():
    completed = subprocess.run(
        [sys.executable, "-I", "-m", "conda_mcp._stdio", "list"],
        input=b"",
        capture_output=True,
        timeout=30,
    )

    assert completed.returncode == 2
    assert completed.stdout == b""
    assert b"This launcher accepts only serve or run." in completed.stderr
