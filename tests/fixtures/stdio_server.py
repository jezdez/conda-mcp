"""A real foreground child for protocol, activation and process-tree checks."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path


def main() -> int:
    mode = os.environ.get("MCP_TEST_MODE", "echo")
    if mode == "tree-child":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        Path(os.environ["MCP_TEST_CHILD_PID"]).write_text(str(os.getpid()))
        while True:
            signal.pause()
    if mode == "tree":
        child = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve())],
            env={**os.environ, "MCP_TEST_MODE": "tree-child"},
        )
        print(json.dumps({"child": child.pid}), flush=True)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        while True:
            signal.pause()
    if mode == "metadata":
        print(
            json.dumps(
                {
                    "argv": sys.argv[1:],
                    "cwd": os.getcwd(),
                    "token": os.environ.get("MCP_TEST_TOKEN"),
                    "reserved": "_CONDA_MCP_LAUNCH" in os.environ,
                    "prefix": os.environ.get("CONDA_PREFIX"),
                }
            ),
            flush=True,
        )
    else:
        print("READY", flush=True)
        for line in sys.stdin.buffer:
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
        print("EOF", flush=True)
    return int(os.environ.get("MCP_TEST_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main())
