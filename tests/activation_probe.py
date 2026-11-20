"""Start an activated test server with real inherited descriptors."""

import sys
from pathlib import Path

from conda_mcp.run import run
from conda_mcp.servers import discover

if __name__ == "__main__":
    sys.exit(run(discover(Path(sys.argv[1]))[0], tuple(sys.argv[2:])))
