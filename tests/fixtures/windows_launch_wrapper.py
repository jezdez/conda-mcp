import json
import os
from pathlib import Path

from conda_mcp._launch_windows import restore_protocol

payload = json.loads(os.environ["_CONDA_MCP_LAUNCH"])
assert payload["fixture"] is True
restore_protocol(payload)
Path(os.environ["WINDOWS_LAUNCH_OUTPUT"]).write_text(
    os.read(0, 3).decode(), encoding="utf-8"
)
os.write(1, b"out")
