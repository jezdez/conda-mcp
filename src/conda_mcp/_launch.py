"""Restore protocol descriptors after activation, then replace this process."""

from __future__ import annotations

import os
import subprocess
import sys

from conda import CondaError

from .run import _PAYLOAD, LaunchPayload


def main() -> int:
    """Revalidate activated inputs before exposing protocol descriptors."""
    try:
        payload = LaunchPayload.decode(os.environ.pop(_PAYLOAD))
        executable = payload.revalidate()
        payload.restore_protocol()
        os.chdir(payload.cwd)
        if os.name == "nt":
            # Windows exec creates a new process and exits immediately. Keep the
            # job-owned trampoline alive until the server's real exit status exists.
            return subprocess.run(
                payload.argv, executable=str(executable), check=False
            ).returncode
        os.execve(str(executable), payload.argv, os.environ)
    except (CondaError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"MCP launch failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
