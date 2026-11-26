"""Start an activated test server with real inherited descriptors."""

import os
import sys
from pathlib import Path

from conda_mcp.run import run
from conda_mcp.servers import discover

if __name__ == "__main__":
    name = os.environ.get("MCP_TEST_SERVER_NAME", "example")
    sys.exit(run(discover(Path(sys.argv[1]), name=name)[0], tuple(sys.argv[2:])))
