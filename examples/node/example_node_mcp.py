"""Launch the packaged JavaScript server with the activated Node runtime."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def main() -> None:
    """Keep protocol streams and return the server's exit status."""
    node = shutil.which("node")
    if node is None:
        raise SystemExit("The Node runtime is missing from the environment.")
    raise SystemExit(
        subprocess.call([node, str(Path(__file__).with_name("server.mjs"))])
    )
